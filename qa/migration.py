"""Motor del Stare and Compare: sitio original contra sitio migrado.

Programa aparte del QA de localizacion, porque la logica de fondo es la
contraria. Alla los dos textos DEBEN diferir y se valida la traduccion contra
el glosario; aca deben ser IGUALES y cualquier diferencia es sospechosa.

Lo que si se reutiliza, sin cambios:

    qa/fetch.py             descarga
    qa/extract.py           unidades de texto y emparejamiento en 4 pasadas
    qa/checks/broken_keys   claves del CMS visibles
    qa/checks/entities      entidades HTML como texto literal
    qa/checks/mojibake      caracteres corruptos
    qa/checks/popups        popups que no llegaron
    qa/browser.py           verificar que los popups abren

Lo que NO aplica: el glosario y la conversion de unidades. Son de traduccion,
y aca no se traduce nada.
"""

import logging
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urljoin

import requests

from qa.checks.broken_keys import find_broken_keys, keys_in
from qa.checks.entities import find_html_entities
from qa.checks.fidelity import compare_counts, compare_texts, find_source_leaks
from qa.checks.links import check_broken_links, check_link_destinations
from qa.checks.mojibake import find_char_issues
from qa.checks.popups import check_popups
from qa.extract import extract_units, make_soup, pair_units, visible_text
from qa.fetch import (fetch_html, make_session, normalize_base_url,
                      polite_pause)
from qa.findings import Finding, Severity, Verdict

logger = logging.getLogger(__name__)

# Los popups los reporta check_popups en un hallazgo con la causa
POPUP_KINDS = {"popup_trigger", "popup_title", "popup_content"}


@dataclass
class PagePair:
    """Un path revisado en los dos sitios."""
    path: str
    source_url: str = ""
    copy_url: str = ""
    findings: list[Finding] = field(default_factory=list)
    units_checked: int = 0
    error: str = ""

    @property
    def errors(self) -> int:
        return sum(1 for f in self.findings if f.severity is Severity.ERROR)


@dataclass
class MigrationResult:
    source_site: str
    copy_site: str
    pages: list[PagePair] = field(default_factory=list)
    error: str = ""

    # Nombres compatibles con qa/export.py, que espera un ScanResult
    @property
    def base_url(self) -> str:
        return self.copy_site

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


def local_filename(path: str) -> str:
    """Nombre de archivo esperado para el HTML de un path guardado a mano.

    El mismo algoritmo lo usa extension/popup.js al exportar: si uno cambia,
    el otro tiene que cambiar igual, o --source-dir no encuentra nada.
    """
    limpio = path.strip("/").replace("/", "_")
    return f"{limpio or 'home'}.html"


def compare_page(source_site: str, copy_site: str, source_path: str, copy_path: str,
                 session: requests.Session, char_rules=None,
                 verify_links: bool = False, link_cache: dict = None,
                 source_dir: str = None) -> PagePair:
    """Compara un path del original contra su equivalente en la copia.

    source_path y copy_path pueden ser distintos: cada plataforma arma sus
    rutas a su manera (el live site suele usar '/seccion/', el CMS
    '/seccion.htm'), asi que no hay garantia de que sea el mismo string en
    los dos lados -- eso lo decide quien arma la lista de paths, no esta
    funcion. El path que identifica la pagina en el reporte es el de la
    copia: es el que un QA va a mirar en el CMS.

    source_dir: cuando el sitio original bloquea pedidos automatizados (por
    ejemplo, un desafio anti-bot), su HTML no se pide por red -- se lee de un
    archivo guardado a mano (ver extension/), buscado por local_filename().
    """
    source_url = urljoin(source_site, source_path.lstrip("/"))
    copy_url = urljoin(copy_site, copy_path.lstrip("/"))
    result = PagePair(path=copy_path, source_url=source_url, copy_url=copy_url)

    copy_html = fetch_html(session, copy_url)
    if copy_html is None:
        result.error = f"Could not fetch the migrated page: {copy_url}"
        return result

    if source_dir:
        archivo = Path(source_dir) / local_filename(source_path)
        if not archivo.exists():
            result.error = (
                f"Source file not found: {archivo}. Save it with the browser "
                "extension (see extension/README.md) and put it in --source-dir."
            )
            return result
        source_html = archivo.read_text(encoding="utf-8")
    else:
        polite_pause()
        source_html = fetch_html(session, source_url)
        if source_html is None:
            result.error = f"Could not fetch the source page: {source_url}"
            return result

    copy_units = extract_units(copy_html, copy_site)
    source_units = extract_units(source_html, source_site)
    result.units_checked = len(copy_units)

    copy_text = visible_text(copy_html)
    source_text = visible_text(source_html)
    source_keys = keys_in(source_text)

    findings: list[Finding] = []

    # --- Daño introducido al copiar ---
    findings += find_broken_keys(copy_text, copy_path, source_keys)
    findings += find_html_entities(copy_text, copy_path)
    findings += find_char_issues(copy_text, char_rules, copy_path)

    # --- El bug clasico de migracion ---
    findings += find_source_leaks(make_soup(copy_html), source_site, copy_path)

    # --- Fidelidad del contenido ---
    pairs, orphans, missing = pair_units(copy_units, source_units)

    # Los popups los cubre su propio check, con la causa en un solo hallazgo
    pairs = [(c, s) for c, s in pairs if c.kind not in POPUP_KINDS]
    orphans = [u for u in orphans if u.kind not in POPUP_KINDS]
    missing = [u for u in missing if u.kind not in POPUP_KINDS]

    findings += compare_texts(source_units, copy_units, pairs, orphans, missing, copy_path)
    findings += compare_counts(source_units, copy_units, copy_path)
    findings += check_popups(copy_units, source_units, copy_path)

    # --- Links: que funcionen, y que lleven al mismo lugar que en el original ---
    # Aparte de los otros checks porque pega al sitio en vivo por cada link, no
    # solo por cada pagina: es lento, por eso queda detras de un flag.
    if verify_links:
        cache = link_cache if link_cache is not None else {}
        findings += check_broken_links(copy_units, copy_site, copy_path, session, cache)
        findings += check_link_destinations(pairs, source_site, copy_site, copy_path, session, cache)

    result.findings = _dedupe(findings)
    return result


def _dedupe(findings: list[Finding]) -> list[Finding]:
    """Un hallazgo por (tipo, texto, pagina), quedandose con el mas informativo."""
    mejores: dict[tuple, Finding] = {}
    orden: list[tuple] = []
    for finding in findings:
        clave = (finding.verdict, finding.found or finding.expected, finding.path)
        anterior = mejores.get(clave)
        if anterior is None:
            mejores[clave] = finding
            orden.append(clave)
        elif finding.expected and not anterior.expected:
            mejores[clave] = finding
    return [mejores[c] for c in orden]


def _normalize_path(p: str) -> str:
    if "://" in p or p.startswith("/"):
        return p
    return "/" + p


def compare_sites(source_site: str, copy_site: str, paths, copy_paths=None,
                  char_rules=None, on_progress=None, mobile: bool = False,
                  verify_links: bool = False, source_dir: str = None) -> MigrationResult:
    """Compara una lista de paths entre los dos sitios.

    Si copy_paths viene, cada path se empareja por POSICION con el de
    paths: paths[i] es la pagina en el sitio original, copy_paths[i] su
    equivalente en la copia. Hace falta cuando las dos plataformas arman las
    rutas distinto (el live site en '/seccion/', el CMS en '/seccion.htm') y
    no hay forma de que un solo string sirva para las dos.

    Sin copy_paths, se asume el mismo path en los dos lados -- el caso comun.

    Si source_dir viene, el HTML del original no se pide por red -- ver
    compare_page().
    """
    source_site = normalize_base_url(source_site)
    copy_site = normalize_base_url(copy_site)
    result = MigrationResult(source_site=source_site, copy_site=copy_site)

    paths = [_normalize_path(p) for p in paths]
    if not paths:
        result.error = "No paths given. Pass at least one with --paths."
        return result

    if copy_paths is not None:
        copy_paths = [_normalize_path(p) for p in copy_paths]
        if len(copy_paths) != len(paths):
            result.error = (
                f"--paths and --copy-paths must have the same number of entries "
                f"({len(paths)} vs {len(copy_paths)})."
            )
            return result
    else:
        copy_paths = paths

    session = make_session(mobile=mobile)
    # Una sola cache de links para toda la corrida: la navegacion se repite en
    # cada pagina, y sin compartirla se verificaria el mismo link una vez por
    # pagina en la que aparece.
    link_cache: dict = {}
    total = len(paths)
    for index, (source_path, copy_path) in enumerate(zip(paths, copy_paths)):
        if index > 0:
            polite_pause()
        logger.info("Comparing %s -> %s (%d/%d)", source_path, copy_path, index + 1, total)
        if on_progress is not None:
            on_progress(index, total, copy_path)
        result.pages.append(compare_page(source_site, copy_site, source_path, copy_path,
                                         session, char_rules,
                                         verify_links=verify_links, link_cache=link_cache,
                                         source_dir=source_dir))

    if on_progress is not None:
        on_progress(total, total, "")

    return result
