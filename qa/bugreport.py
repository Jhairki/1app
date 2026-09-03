"""Traduce un hallazgo al formato de bugs del equipo.

    Field 1 | Field 2 | Field 3 | Field 4
       D    | Critical|  Link   | The CTA is not performing any action.

    Field 1  dispositivo   D (Desktop) o M (Mobile)
    Field 2  importancia   Critical, Issue o Question
    Field 3  tipo          Content, Config, Link, Label o Styling
    Field 4  descripcion   texto libre

La idea es que el reporte se pueda pegar tal cual en el tracker, sin que nadie
tenga que reescribir cada hallazgo a mano.

Field 2 sigue la definicion del documento: Critical para lo serio, Issue para
lo menor, y Question cuando no se sabe si es un bug o una decision del builder.
Esa ultima definicion es la que decide varios de los mapeos de abajo.

Field 4 reusa el vocabulario de la lista de bugs recurrentes del equipo
-- Missing Content, Wrong Content, Broken Label, External Link needed -- para
que el reporte hable como ellos ya hablan.
"""

from qa.findings import Finding, Severity, Verdict

DESKTOP = "D"
MOBILE = "M"

CRITICAL = "Critical"
ISSUE = "Issue"
QUESTION = "Question"

CONTENT = "Content"
# El documento dice "Config", pero en los reportes reales del equipo
# figura escrito completo. Se usa el que ellos tipean.
CONFIG = "Configuration"
LINK = "Link"
LABEL = "Label"
STYLING = "Styling"

# (Field 2, Field 3, frase corta para el Field 4)
MAPEO = {
    # --- Claves del CMS y labels ---
    Verdict.BROKEN_KEY:        (CRITICAL, LABEL,   "Broken Label"),
    # No abre en ingles tampoco: puede ser decision del builder, no se sabe
    Verdict.BROKEN_KEY_SOURCE: (QUESTION, LABEL,   "Broken Label on both locales"),

    # --- Contenido faltante o alterado ---
    Verdict.MISSING:           (CRITICAL, CONTENT, "Missing Content"),
    Verdict.CONTENT_MISSING:   (CRITICAL, CONTENT, "Missing Content"),
    Verdict.TEXT_CHANGED:      (CRITICAL, CONTENT, "Wrong Content"),
    Verdict.UNTRANSLATED:      (CRITICAL, CONTENT, "Wrong Content, still in English"),
    Verdict.CONTENT_EXTRA:     (QUESTION, CONTENT, "Extra content not on the source"),
    Verdict.COUNT_MISMATCH:    (QUESTION, CONTENT, "Section may be missing"),

    # --- Traduccion contra el glosario ---
    Verdict.OFF_GLOSSARY:      (ISSUE,    CONTENT, "Wrong Content, off glossary"),
    Verdict.NEAR_MISS:         (ISSUE,    CONTENT, "Wrong Content, close to the glossary term"),
    Verdict.PROPER_NOUN_ALTERED: (ISSUE,  CONTENT, "Wrong Content, model name altered"),
    Verdict.DUPLICATE_TERM:    (ISSUE,    CONTENT, "Duplicated term on the page"),
    Verdict.ACCEPTED_VARIANT:  (QUESTION, CONTENT, "Accepted variant, not the official term"),
    Verdict.UNKNOWN_TERM:      (QUESTION, CONTENT, "Term not in the glossary"),

    # --- Presentacion ---
    Verdict.CASE_MISMATCH:     (ISSUE,    STYLING, "Capitalization does not match"),

    # --- Caracteres ---
    Verdict.MOJIBAKE:          (ISSUE,    CONTENT, "Broken character"),
    Verdict.HTML_ENTITY:       (ISSUE,    CONTENT, "HTML entity showing as text"),
    Verdict.LOST_CHAR:         (ISSUE,    CONTENT, "Lost character"),

    # --- Enlaces ---
    Verdict.SOURCE_LEAK:       (CRITICAL, LINK,    "External Link needed"),
    Verdict.BROKEN_LINK:       (CRITICAL, LINK,    "Broken Link"),
    # Se decide por parecido de titulo, no por una regla exacta -- puede ser un
    # link mal armado o simplemente una pagina que se llama distinto. Question,
    # no Critical, hasta que alguien lo mire.
    Verdict.LINK_MISMATCH:     (QUESTION, LINK,    "Link may lead to the wrong page"),

    # --- Popups ---
    Verdict.POPUP_MISSING:     (CRITICAL, CONTENT, "Missing Content, popup not migrated"),
    Verdict.POPUP_BROKEN:      (CRITICAL, CONFIG,  "The CTA is not performing any action"),
    Verdict.POPUP_BROKEN_SOURCE: (QUESTION, CONFIG, "Popup does not open on either site"),
    Verdict.POPUP_EXTRA:       (QUESTION, CONTENT, "Popup only on this site"),
    Verdict.POPUP_UNVERIFIED:  (QUESTION, CONFIG,  "Popup could not be verified"),

    # --- Configuracion del sitio ---
    Verdict.LOCALE_NOT_APPLIED: (CRITICAL, CONFIG, "The locale switch is not working"),
    Verdict.UNIT_NOT_CONVERTED: (CRITICAL, CONTENT, "Wrong Content, value not converted"),
    Verdict.UNIT_MISLABELED:   (CRITICAL, CONTENT, "Wrong Content, unit mislabeled"),
    Verdict.UNIT_UNVERIFIABLE: (QUESTION, CONTENT, "Value could not be verified"),
    Verdict.STYLE_VIOLATION:   (ISSUE,    STYLING, "Style rule not followed"),
}

# Si algun veredicto no esta mapeado, se cae a la severidad
POR_SEVERIDAD = {
    Severity.ERROR: (CRITICAL, CONTENT),
    Severity.WARNING: (ISSUE, CONTENT),
    Severity.INFO: (QUESTION, CONTENT),
}


def classify(finding: Finding) -> tuple[str, str, str]:
    """Devuelve (Field 2, Field 3, frase corta) para un hallazgo."""
    if finding.verdict in MAPEO:
        return MAPEO[finding.verdict]
    importancia, tipo = POR_SEVERIDAD.get(finding.severity, (ISSUE, CONTENT))
    return importancia, tipo, finding.verdict.value.replace("_", " ").capitalize()


def describe(finding: Finding, frase: str) -> str:
    """El Field 4: la frase corta del equipo, mas lo concreto del hallazgo."""
    partes = [frase]

    if finding.found and finding.expected:
        partes.append(f'"{finding.found}" should be "{finding.expected}"')
    elif finding.expected:
        partes.append(f'"{finding.expected}" is not on the page')
    elif finding.found:
        partes.append(f'"{finding.found}"')

    if finding.context:
        partes.append(f"({finding.context})")

    texto = " — ".join(partes[:2])
    if len(partes) > 2:
        texto += " " + partes[2]
    return texto


def to_bug(finding: Finding, device: str = DESKTOP) -> str:
    """El hallazgo como una linea lista para pegar en el tracker."""
    importancia, tipo, frase = classify(finding)
    return f"{device} | {importancia} | {tipo} | {describe(finding, frase)}"


def to_bug_fields(finding: Finding, device: str = DESKTOP) -> dict:
    """Los cuatro campos por separado, para el CSV."""
    importancia, tipo, frase = classify(finding)
    return {
        "field_1_device": device,
        "field_2_importance": importancia,
        "field_3_type": tipo,
        "field_4_description": describe(finding, frase),
    }


def group_repeated(result, device: str = DESKTOP) -> list[dict]:
    """Agrupa los hallazgos identicos que aparecen en varias paginas.

    El documento pide justamente esto: "If you find the same bug on multiple
    pages, chat with the person who worked on the request." Un bug que sale en
    30 paginas es casi siempre un solo elemento de la navegacion, y reportarlo
    30 veces es ruido.
    """
    grupos: dict[str, dict] = {}
    for page in result.pages:
        for finding in page.findings:
            linea = to_bug(finding, device)
            entrada = grupos.setdefault(linea, {"bug": linea, "paths": [],
                                                "verdict": finding.verdict.value})
            if page.path not in entrada["paths"]:
                entrada["paths"].append(page.path)

    orden = {CRITICAL: 0, ISSUE: 1, QUESTION: 2}
    return sorted(
        grupos.values(),
        key=lambda g: (orden.get(g["bug"].split(" | ")[1], 3), -len(g["paths"])),
    )
