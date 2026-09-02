"""Check: el mismo concepto repetido dentro de la pagina española.

Encontrado en un sitio real. La lista de carrocerias en español traia:

    Camion, Convertible, Coupe, Coupe(acento), Descapotable, Furgoneta, VUD

contra las 5 del ingles. O sea 'Coupe' sin traducir Y 'Coupé' traducida, las
dos visibles al usuario. Ese bug no lo ve ningun check que compare ES contra EN,
porque el problema esta ENTRE dos textos del lado español.

Dos señales, ambas con evidencia dura -- nada de "se parecen":

  1. Dos textos identicos salvo por los acentos ('Coupe' / 'Coupé').
     Es el mismo termino escrito dos veces, una sin acentuar.

  2. Un texto es la clave inglesa del glosario y otro es su traduccion
     canonica, los dos en la misma pagina ('Service' junto a 'Mantenimiento').
"""

from qa.findings import Finding, Severity, Verdict
from qa.glossary import Policy
from qa.normalize import differs_only_by_accent, normalize, normalize_display


def find_duplicates(units, glossary, path: str = "") -> list[Finding]:
    """Busca el mismo concepto escrito dos veces en la pagina española."""
    textos: dict[str, object] = {}
    for unit in units:
        clave = normalize(unit.text)
        if clave and clave not in textos:
            textos[clave] = unit

    findings: list[Finding] = []
    reportados: set[tuple[str, str]] = set()
    claves = list(textos)

    # --- 1. Iguales salvo acentos ---
    for i, a in enumerate(claves):
        for b in claves[i + 1:]:
            if not differs_only_by_accent(a, b):
                continue
            par = tuple(sorted((a, b)))
            if par in reportados:
                continue
            reportados.add(par)

            unit_a, unit_b = textos[a], textos[b]
            findings.append(
                Finding(
                    verdict=Verdict.DUPLICATE_TERM,
                    severity=Severity.ERROR,
                    found=f"{normalize_display(unit_a.text)}  /  {normalize_display(unit_b.text)}",
                    path=path,
                    auto_fixable=False,
                    message=(
                        "The same term appears twice on the page, one version with accents "
                        "and one without. Only one should remain."
                    ),
                    context=f"{unit_a.describe()} y {unit_b.describe()}",
                    meta={"a": unit_a.text, "b": unit_b.text, "reason": "accent"},
                )
            )

    # --- 2. La clave inglesa y su traduccion, las dos presentes ---
    for entry in glossary.entries:
        if entry.policy is not Policy.TRANSLATE or not entry.spanish_canonical:
            continue
        clave_en = normalize(entry.english)
        clave_es = normalize(entry.spanish_canonical)
        if clave_en == clave_es:
            continue
        if clave_en in textos and clave_es in textos:
            unit_en, unit_es = textos[clave_en], textos[clave_es]
            findings.append(
                Finding(
                    verdict=Verdict.DUPLICATE_TERM,
                    severity=Severity.ERROR,
                    found=f"{normalize_display(unit_en.text)}  /  {normalize_display(unit_es.text)}",
                    expected=entry.spanish_canonical,
                    path=path,
                    auto_fixable=False,
                    message=(
                        f"The page shows the term in English ({entry.english!r}) and also "
                        f"translated ({entry.spanish_canonical!r}). The English one is redundant."
                    ),
                    context=f"{unit_en.describe()} y {unit_es.describe()}",
                    meta={"english": entry.english, "spanish": entry.spanish_canonical,
                          "reason": "both_languages"},
                )
            )

    return findings
