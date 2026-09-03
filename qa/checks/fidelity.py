"""Checks del Stare and Compare: la copia contra el original.

La diferencia de fondo con el QA de localizacion: alla los dos textos DEBEN
ser distintos y lo que se valida es que la traduccion siga el glosario. Aca los
dos textos deben ser IGUALES, y cualquier diferencia es sospechosa.

Eso hace el criterio mucho mas estricto y mucho mas simple: no hace falta
glosario ni umbrales de parecido. Se compara y se reporta.

El check propio de una migracion, y el que mas encuentra, es el ultimo: enlaces
e imagenes de la pagina nueva que siguen apuntando al sitio viejo. Esos no se
notan mirando -- la pagina se ve perfecta -- hasta que el sitio viejo se apaga.
"""

import re
from urllib.parse import urlparse

from qa.findings import Finding, Severity, Verdict
from qa.normalize import normalize, normalize_display

# Atributos donde puede quedar escondida una URL del sitio viejo
URL_ATTRS = ("href", "src", "data-href", "data-src", "srcset", "action", "poster")

# Diferencias que no valen la pena reportar: solo espacios o puntuacion suelta
SOLO_RUIDO = re.compile(r"^[\s\W_]*$")


def _mismo_texto(a: str, b: str) -> bool:
    return normalize(a) == normalize(b)


def compare_texts(source_units, copy_units, pairs, orphans, missing,
                  path: str = "") -> list[Finding]:
    """Compara el texto de cada elemento emparejado, y lo que no aparea.

    pairs viene como (unidad_de_la_copia, unidad_del_original), igual que en el
    motor de localizacion: el primer elemento es el que se esta revisando.
    """
    findings: list[Finding] = []

    for unit_copy, unit_source in pairs:
        if _mismo_texto(unit_copy.text, unit_source.text):
            continue

        findings.append(
            Finding(
                verdict=Verdict.TEXT_CHANGED,
                severity=Severity.ERROR,
                found=normalize_display(unit_copy.text),
                expected=normalize_display(unit_source.text),
                path=path,
                auto_fixable=True,
                fixed=normalize_display(unit_source.text),
                message=(
                    "The text differs from the source site. In a same-language "
                    "migration the copy should match the original exactly."
                ),
                context=unit_copy.describe(),
                meta={"kind": unit_copy.kind, "key": unit_copy.key},
            )
        )

    for unit in missing:
        if SOLO_RUIDO.match(unit.text or ""):
            continue
        findings.append(
            Finding(
                verdict=Verdict.CONTENT_MISSING,
                severity=Severity.ERROR,
                found="",
                expected=normalize_display(unit.text),
                path=path,
                auto_fixable=False,
                message=(
                    f"Present on the source site but not on the migrated page: "
                    f"{unit.text!r} ({unit.describe()})."
                ),
                context=unit.describe(),
                meta={"kind": unit.kind, "key": unit.key},
            )
        )

    for unit in orphans:
        if SOLO_RUIDO.match(unit.text or ""):
            continue
        findings.append(
            Finding(
                verdict=Verdict.CONTENT_EXTRA,
                severity=Severity.WARNING,
                found=normalize_display(unit.text),
                path=path,
                auto_fixable=False,
                message=(
                    f"On the migrated page but not on the source site: "
                    f"{unit.text!r} ({unit.describe()}). It may be intentional new "
                    "content, or an element that did not pair."
                ),
                context=unit.describe(),
                meta={"kind": unit.kind, "key": unit.key},
            )
        )

    return findings


def _dominio(url: str) -> str:
    return (urlparse(url).netloc or url).lower().removeprefix("www.")


def find_source_leaks(soup, source_url: str, path: str = "") -> list[Finding]:
    """URLs de la pagina nueva que siguen apuntando al sitio viejo.

    Es el bug clasico de una migracion y no se nota mirando: la pagina se ve
    perfecta porque el sitio viejo todavia responde. Se rompe el dia que lo
    apagan.
    """
    dominio = _dominio(source_url)
    if not dominio:
        return []

    findings: list[Finding] = []
    vistos: set[tuple[str, str]] = set()

    for el in soup.find_all(True):
        for attr in URL_ATTRS:
            valor = el.get(attr)
            if not valor or not isinstance(valor, str):
                continue
            if dominio not in valor.lower():
                continue

            clave = (attr, valor)
            if clave in vistos:
                continue
            vistos.add(clave)

            etiqueta = el.get_text(strip=True)[:60] or el.get("alt", "")[:60]
            findings.append(
                Finding(
                    verdict=Verdict.SOURCE_LEAK,
                    severity=Severity.ERROR,
                    found=valor[:180],
                    path=path,
                    auto_fixable=False,
                    message=(
                        f"<{el.name} {attr}> still points at the source site "
                        f"({dominio}). The page looks fine only while the old site "
                        "is still up."
                    ),
                    context=f"<{el.name} {attr}>" + (f" — {etiqueta!r}" if etiqueta else ""),
                    meta={"tag": el.name, "attr": attr, "url": valor,
                          "source_domain": dominio},
                )
            )

    return findings


def compare_counts(source_units, copy_units, path: str = "") -> list[Finding]:
    """Aviso cuando un tipo de elemento cambia mucho de cantidad.

    Sirve de red: si el emparejamiento falla por completo en alguna seccion, los
    hallazgos individuales pueden ser enganosos, pero el conteo lo delata.
    """
    def por_tipo(units):
        conteo: dict[str, int] = {}
        for u in units:
            conteo[u.kind] = conteo.get(u.kind, 0) + 1
        return conteo

    origen, copia = por_tipo(source_units), por_tipo(copy_units)
    findings: list[Finding] = []

    for kind in sorted(set(origen) | set(copia)):
        n_origen, n_copia = origen.get(kind, 0), copia.get(kind, 0)
        if n_origen == n_copia:
            continue
        # Solo se avisa cuando la diferencia es grande: los sitios reales
        # tienen variaciones chicas legitimas.
        if abs(n_origen - n_copia) < max(3, 0.2 * max(n_origen, n_copia)):
            continue

        findings.append(
            Finding(
                verdict=Verdict.COUNT_MISMATCH,
                severity=Severity.WARNING,
                found=f"{n_copia} {kind}",
                expected=f"{n_origen} {kind}",
                path=path,
                auto_fixable=False,
                message=(
                    f"The source site has {n_origen} elements of type {kind!r} and the "
                    f"migrated page has {n_copia}. A gap this wide usually means a "
                    "whole section is missing or did not pair."
                ),
                context=f"count of {kind}",
                meta={"kind": kind, "source": n_origen, "copy": n_copia},
            )
        )

    return findings
