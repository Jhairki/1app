"""Motor de QA: junta los seis checks sobre cada pagina.

Por cada path del sitio se traen DOS paginas -- ?locale=es_US y ?locale=en_US --
y se comparan. La pagina inglesa no es decorativa: es la referencia contra la
que se decide si el español esta sin traducir, si las mayusculas siguen el
patron, si la conversion de unidades se hizo, y si falta contenido.

Checks que corren sobre el texto completo (no necesitan par):
  1. claves internas del CMS
  2. entidades HTML visibles
  3. mojibake y caracteres perdidos

Checks que necesitan el par EN:
  4. termino contra el glosario, y mayusculas
  5. unidades millas/kilometros
  6. contenido que existe en ingles y no en español
"""

import logging
from dataclasses import dataclass, field
from difflib import SequenceMatcher

from qa.checks.broken_keys import find_broken_keys, is_broken_key, keys_in
from qa.checks.duplicates import find_duplicates
from qa.checks.entities import find_html_entities
from qa.checks.mojibake import find_char_issues
from qa.checks.terms import TermChecker
from qa.checks.units import check_units
from qa.extract import extract_units, find_navigation_paths, pair_units, visible_text
from qa.fetch import (
    ENGLISH,
    SPANISH,
    fetch_html,
    make_session,
    normalize_base_url,
    polite_pause,
    with_locale,
)
from qa.findings import Finding, Severity, Verdict
from qa.glossary import Glossary, load_glossary

logger = logging.getLogger(__name__)

# Veredictos que no son hallazgos: no se reportan, solo se cuentan
CLEAN_VERDICTS = {Verdict.OK}

# En una pagina real los unknown_term son el 76% del reporte: nombres de
# modelos, direcciones, telefonos, copy de marketing. Nada de eso va a estar
# nunca en un glosario de labels. Se ocultan salvo que se pidan a proposito,
# porque sirven para hacer crecer el glosario, no para revisar una pagina.
NOISY_VERDICTS = {Verdict.UNKNOWN_TERM}

# Unidades cuyo texto vive en atributos, fuera del cuerpo de la pagina
ATTRIBUTE_KINDS = {"meta", "image_alt"}

# Si la pagina ES y la EN son practicamente el mismo texto, el sitio ignoro el
# parametro locale. Sin esto, cada termino del glosario saldria como
# "untranslated" y el reporte tendria cientos de hallazgos con una sola causa.
IDENTICAL_PAGE_RATIO = 0.98


def _es_contenido(texto: str) -> bool:
    """Filtra lo que no es contenido para el usuario.

    Los carruseles numeran sus puntos ('1', '2', '3'): reportar que falta el
    '4' de la paginacion no le sirve a nadie.
    """
    limpio = (texto or "").strip()
    return len(limpio) > 1 and not limpio.replace(".", "").replace(",", "").isdigit()


@dataclass
class PageResult:
    path: str
    spanish_url: str = ""
    english_url: str = ""
    findings: list[Finding] = field(default_factory=list)
    units_checked: int = 0
    error: str = ""

    @property
    def errors(self) -> int:
        return sum(1 for f in self.findings if f.severity is Severity.ERROR)


@dataclass
class ScanResult:
    base_url: str
    pages: list[PageResult] = field(default_factory=list)
    glossary_issues: list = field(default_factory=list)
    error: str = ""

    @property
    def findings(self) -> list[Finding]:
        return [f for page in self.pages for f in page.findings]

    def summary(self) -> dict:
        findings = self.findings
        by_verdict: dict[str, int] = {}
        for finding in findings:
            by_verdict[finding.verdict.value] = by_verdict.get(finding.verdict.value, 0) + 1

        return {
            "pages_scanned": len([p for p in self.pages if not p.error]),
            "pages_failed": len([p for p in self.pages if p.error]),
            "units_checked": sum(p.units_checked for p in self.pages),
            "total_findings": len(findings),
            "errors": sum(1 for f in findings if f.severity is Severity.ERROR),
            "warnings": sum(1 for f in findings if f.severity is Severity.WARNING),
            "infos": sum(1 for f in findings if f.severity is Severity.INFO),
            "affected_pages": len({f.path for f in findings if f.severity is Severity.ERROR}),
            "auto_fixable": sum(1 for f in findings if f.auto_fixable),
            "by_verdict": dict(sorted(by_verdict.items(), key=lambda kv: -kv[1])),
        }


def scan_page(base_url: str, path: str, glossary: Glossary, checker: TermChecker,
              session, report_unknown: bool = False) -> PageResult:
    """Corre los seis checks sobre un path del sitio."""
    spanish_url = with_locale(base_url, path, SPANISH)
    english_url = with_locale(base_url, path, ENGLISH)
    result = PageResult(path=path, spanish_url=spanish_url, english_url=english_url)

    spanish_html = fetch_html(session, spanish_url)
    if spanish_html is None:
        result.error = f"No se pudo traer la pagina en español: {spanish_url}"
        return result

    polite_pause()
    english_html = fetch_html(session, english_url)
    if english_html is None:
        logger.warning("Sin pagina EN para %s: se corren solo los checks sin par", path)

    spanish_text = visible_text(spanish_html)
    english_text = visible_text(english_html) if english_html else ""

    skip = CLEAN_VERDICTS if report_unknown else CLEAN_VERDICTS | NOISY_VERDICTS

    findings: list[Finding] = []
    spanish_units = extract_units(spanish_html, base_url)
    result.units_checked = len(spanish_units)

    # Las claves que ya estan rotas en ingles no son bug de traduccion
    english_keys = keys_in(english_text) if english_text else set()

    # --- Checks sobre el texto completo ---
    findings += find_broken_keys(spanish_text, path, english_keys)
    findings += find_html_entities(spanish_text, path)
    findings += find_char_issues(spanish_text, glossary.char_rules, path)
    findings += find_duplicates(spanish_units, glossary, path)

    # visible_text solo trae el cuerpo. Los metadatos y el alt de las imagenes
    # viven en atributos, asi que se revisan aparte o se escapan del check.
    for unit in spanish_units:
        if unit.kind not in ATTRIBUTE_KINDS:
            continue
        attribute_findings = (
            find_broken_keys(unit.text, path, english_keys)
            + find_html_entities(unit.text, path)
            + find_char_issues(unit.text, glossary.char_rules, path)
        )
        for finding in attribute_findings:
            finding.context = f"{unit.describe()} | {finding.context}".strip(" |")
            findings.append(finding)

    # --- El locale se aplico? ---
    locale_ignored = False
    if english_html and spanish_text and english_text:
        if spanish_text == english_text:
            locale_ignored = True
        else:
            ratio = SequenceMatcher(None, spanish_text[:4000], english_text[:4000]).ratio()
            locale_ignored = ratio >= IDENTICAL_PAGE_RATIO

    if locale_ignored:
        findings.append(
            Finding(
                verdict=Verdict.LOCALE_NOT_APPLIED,
                severity=Severity.ERROR,
                found=spanish_url,
                expected=english_url,
                path=path,
                auto_fixable=False,
                message=(
                    "La pagina en español es identica a la inglesa: el sitio ignoro "
                    "?locale=es_US. No se corrieron los checks de traduccion porque "
                    "marcarian todo el contenido, con una sola causa de fondo."
                ),
                context="revisa como cambia de idioma este sitio",
            )
        )

    # --- Checks que necesitan el par EN ---
    if english_html and not locale_ignored:
        findings += check_units(spanish_text, english_text, path)

        english_units = extract_units(english_html, base_url)
        pairs, orphans, missing = pair_units(spanish_units, english_units)

        for spanish_unit, english_unit in pairs:
            # Una clave cruda no es una mala traduccion, pero ahora que tenemos
            # el par sabemos QUE deberia decir: lo que dice la pagina inglesa.
            if is_broken_key(spanish_unit.text):
                if not is_broken_key(english_unit.text):
                    findings.append(
                        Finding(
                            verdict=Verdict.BROKEN_KEY,
                            severity=Severity.ERROR,
                            found=spanish_unit.text,
                            expected=english_unit.text,
                            path=path,
                            auto_fixable=False,
                            message=(
                                f"Clave del CMS sin traducir. En ingles este mismo "
                                f"elemento dice {english_unit.text!r}."
                            ),
                            context=spanish_unit.describe(),
                            meta={"english": english_unit.text},
                        )
                    )
                continue
            finding = checker.check(spanish_unit.text, english_unit.text, path)
            if finding.verdict not in skip:
                finding.context = f"{spanish_unit.describe()} | {finding.context}".strip(" |")
                findings.append(finding)

        # Sin par EN solo se puede juzgar el texto ES por si mismo
        for unit in orphans:
            if is_broken_key(unit.text):
                continue
            finding = checker.check(unit.text, "", path)
            if finding.verdict not in skip:
                finding.context = f"{unit.describe()} | {finding.context}".strip(" |")
                findings.append(finding)

        # Contenido que esta en ingles y no llego al español
        for unit in missing:
            if not _es_contenido(unit.text):
                continue
            findings.append(
                Finding(
                    verdict=Verdict.MISSING,
                    severity=Severity.ERROR,
                    found="",
                    expected=unit.text,
                    path=path,
                    auto_fixable=False,
                    message=(
                        f"Existe en la pagina en ingles pero no en la española: "
                        f"{unit.text!r} ({unit.describe()})."
                    ),
                    context=unit.describe(),
                )
            )
    elif not locale_ignored:
        # Sin pagina EN: se juzga el texto español por si mismo
        for unit in spanish_units:
            if is_broken_key(unit.text):
                continue
            finding = checker.check(unit.text, "", path)
            if finding.verdict not in skip:
                finding.context = f"{unit.describe()} | {finding.context}".strip(" |")
                findings.append(finding)

    result.findings = _dedupe(findings)
    return result


def _dedupe(findings: list[Finding]) -> list[Finding]:
    """Un hallazgo por (tipo, texto, pagina), quedandose con el mas informativo.

    Una clave del CMS se detecta dos veces: al escanear el texto completo y al
    emparejar el elemento con su equivalente ingles. La segunda es mejor porque
    trae que deberia decir, asi que gana.
    """
    mejores: dict[tuple, Finding] = {}
    orden: list[tuple] = []

    for finding in findings:
        # 'found or expected': los hallazgos de contenido faltante tienen found
        # vacio, asi que sin esto se colapsarian todos en uno solo.
        clave = (finding.verdict, finding.found or finding.expected, finding.path)
        anterior = mejores.get(clave)
        if anterior is None:
            mejores[clave] = finding
            orden.append(clave)
        elif finding.expected and not anterior.expected:
            mejores[clave] = finding

    return [mejores[c] for c in orden]


def scan_site(base_url: str, paths=None, glossary: Glossary = None,
              glossary_issues=None, max_pages: int = 0, on_progress=None,
              report_unknown: bool = False) -> ScanResult:
    """Escanea el sitio completo. Si no se pasan paths, los saca de la navegacion."""
    base_url = normalize_base_url(base_url)

    if glossary is None:
        glossary, glossary_issues = load_glossary()

    result = ScanResult(base_url=base_url, glossary_issues=glossary_issues or [])
    session = make_session()
    checker = TermChecker(glossary)

    if paths is None:
        home_html = fetch_html(session, with_locale(base_url, "/", SPANISH))
        if home_html is None:
            result.error = f"No se pudo traer la portada de {base_url}"
            return result
        paths = find_navigation_paths(home_html, base_url)
        if not paths:
            result.error = (
                "No se encontro navegacion en la portada "
                "(se busco div.header-navigation y luego <nav>)."
            )
            return result
        if "/" not in paths:
            paths.insert(0, "/")

    if max_pages:
        paths = paths[:max_pages]

    for index, path in enumerate(paths):
        if index > 0:
            polite_pause()
        logger.info("Escaneando %s (%d/%d)", path, index + 1, len(paths))
        if on_progress is not None:
            on_progress(index, len(paths), path)
        result.pages.append(
            scan_page(base_url, path, glossary, checker, session, report_unknown)
        )

    if on_progress is not None:
        on_progress(len(paths), len(paths), "")

    return result
