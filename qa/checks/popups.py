"""Check: los popups de la pagina inglesa existen en la española.

Un popup es invisible para los demas checks: su texto vive en atributos
(data-title, data-content) o en un div oculto, no en el cuerpo de la pagina.
Y su ausencia tampoco se nota, porque no deja ningun hueco visible.

Encontrado en la pagina de ejemplos de un sitio real:

    ingles : 4 popovers + 6 dialogos
    español: 0 popovers + 0 dialogos

No era que estuvieran mal traducidos: no se migro ninguno.

Lo que NO cuenta como popup: en esa misma pagina hay siete <a class="btn"> que
parecen botones de popup y no tienen ningun atributo data-*. Ignorarlos es
parte del check.
"""

from qa.extract import POPUP_KINDS
from qa.findings import Finding, Severity, Verdict

# Como se llama cada familia en el reporte
FAMILIAS = {
    "popover": "popover",
    "tooltip": "tooltip",
    "modal": "modal",
    "dialog": "dialog",
}


def _familia(key: str) -> str:
    prefijo = key.split(":")[0].split("#")[0]
    return FAMILIAS.get(prefijo, prefijo)


def inventory(units) -> dict[str, dict]:
    """Los popups de una pagina, indexados por su clave.

    Devuelve {clave: {familia, disparador, titulo, contenido}}.
    """
    popups: dict[str, dict] = {}
    for unit in units:
        if unit.kind not in POPUP_KINDS:
            continue
        entrada = popups.setdefault(
            unit.key,
            {"familia": _familia(unit.key), "disparador": "", "titulo": "", "contenido": ""},
        )
        campo = {"popup_trigger": "disparador",
                 "popup_title": "titulo",
                 "popup_content": "contenido"}[unit.kind]
        if not entrada[campo]:
            entrada[campo] = unit.text
    return popups


def _describe(clave: str, datos: dict) -> str:
    partes = [f"{datos['familia']} {clave}"]
    if datos["disparador"]:
        partes.append(f"trigger {datos['disparador']!r}")
    if datos["titulo"]:
        partes.append(f"title {datos['titulo']!r}")
    return " | ".join(partes)


def check_popups(spanish_units, english_units, path: str = "") -> list[Finding]:
    """Compara el inventario de popups entre los dos idiomas."""
    es = inventory(spanish_units)
    en = inventory(english_units)

    if not es and not en:
        return []

    findings: list[Finding] = []

    # Ninguno se migro: un solo hallazgo, no uno por popup
    if en and not es:
        familias: dict[str, int] = {}
        for datos in en.values():
            familias[datos["familia"]] = familias.get(datos["familia"], 0) + 1
        detalle = ", ".join(f"{n} {f}{'s' if n > 1 else ''}" for f, n in sorted(familias.items()))
        return [
            Finding(
                verdict=Verdict.POPUP_MISSING,
                severity=Severity.ERROR,
                found="",
                expected=detalle,
                path=path,
                auto_fixable=False,
                message=(
                    f"The English page has {len(en)} popups ({detalle}) and the Spanish "
                    "page has none. Not a single one was migrated."
                ),
                context="popup inventory",
                meta={"en": len(en), "es": 0, "familias": familias},
            )
        ]

    # Faltantes uno por uno
    for clave, datos in en.items():
        if clave in es:
            continue
        findings.append(
            Finding(
                verdict=Verdict.POPUP_MISSING,
                severity=Severity.ERROR,
                found="",
                expected=datos["titulo"] or datos["disparador"] or clave,
                path=path,
                auto_fixable=False,
                message=(
                    f"This {datos['familia']} exists in English but not in Spanish: "
                    f"{_describe(clave, datos)}."
                ),
                context=f"popup {clave}",
                meta={"familia": datos["familia"], **datos},
            )
        )

    # De mas en español: puede ser una clave distinta, no necesariamente un error
    for clave, datos in es.items():
        if clave in en:
            continue
        findings.append(
            Finding(
                verdict=Verdict.POPUP_EXTRA,
                severity=Severity.WARNING,
                found=datos["titulo"] or datos["disparador"] or clave,
                path=path,
                auto_fixable=False,
                message=(
                    f"This {datos['familia']} is in Spanish but not in English: "
                    f"{_describe(clave, datos)}. The CMS may have given it a "
                    "different key, not necessarily that it is redundant."
                ),
                context=f"popup {clave}",
                meta={"familia": datos["familia"], **datos},
            )
        )

    return findings
