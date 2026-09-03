"""Verifica que los links del sitio migrado funcionen y lleven al lugar correcto.

Dos problemas de una migracion que no se notan mirando la pagina:

1. Un link que quedo mal armado (path que no sigue la convencion del CMS
   nuevo, o simplemente se corto al copiar) y da 404 en el sitio nuevo.
2. Un link que "funciona" -- responde 200 -- pero lleva a otro lugar: el
   label sigue diciendo lo mismo pero el href se cableo mal y ahora abre otra
   seccion del sitio.

El primero se decide pidiendole la URL al servidor: no hace falta adivinar si
un path "parece" de este CMS (por ejemplo, si termina en .htm), alcanza con
verificar que de verdad resuelve -- eso agarra tanto el path mal formado como
cualquier otro que sea invalido por una razon distinta.

El segundo compara el <title> (o, si no hay, el <h1>) de la pagina de destino
entre el sitio original y el migrado. No la URL -- cada plataforma arma sus
rutas distinto -- sino lo que esa pagina dice de si misma. Como en un Stare
and Compare el contenido debe ser IDENTICO, no una traduccion, ese titulo
deberia sobrevivir la copia casi textual; si no se parece nada, el link
probablemente aterriza en la seccion equivocada.
"""

import logging
import time
from difflib import SequenceMatcher

import requests

from qa.extract import make_soup
from qa.findings import Finding, Severity, Verdict
from qa.normalize import normalize_display

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT_SECONDS = 15

# Pausa entre pedidos de VERIFICACION de link (no los de traer la pagina
# completa, que ya tienen la suya en fetch.py). Son muchos pedidos chicos:
# una pausa mas corta alcanza para no golpear el sitio.
LINK_CHECK_DELAY_SECONDS = 0.3

# Que tan parecidos tienen que ser los titulos de destino para darlos por
# buenos. Mas laxo que TEXT_PAIR_RATIO (0.85) porque el <title> a veces suma
# un sufijo de sitio que cambia entre plataformas ("| Mojix Chevrolet" vs
# "- Mojix Chevrolet, Las Vegas"), pero un valor bajo ya distingue "Used
# Inventory" de "Schedule Service".
TITLE_MATCH_RATIO = 0.55


def _title_of(html: str) -> str:
    soup = make_soup(html)
    if soup.title and soup.title.get_text(strip=True):
        return soup.title.get_text(strip=True)
    h1 = soup.find("h1")
    return h1.get_text(strip=True) if h1 else ""


def _check_url(url: str, session: requests.Session, cache: dict) -> tuple[int, str]:
    """Trae status + titulo de una URL, cacheado.

    El mismo link de navegacion aparece en cada pagina comparada -- sin cache
    se pediria una vez por pagina, multiplicando los pedidos por nada.
    """
    if url in cache:
        return cache[url]

    if cache:  # no pausar antes del primerisimo pedido
        time.sleep(LINK_CHECK_DELAY_SECONDS)

    try:
        response = session.get(url, timeout=REQUEST_TIMEOUT_SECONDS)
        resultado = (response.status_code, _title_of(response.text) if response.ok else "")
    except requests.RequestException as exc:
        logger.info("No se pudo verificar el link %s: %s", url, exc)
        resultado = (0, "")

    cache[url] = resultado
    return resultado


def check_broken_links(copy_units, copy_site: str, path: str,
                       session: requests.Session, cache: dict) -> list[Finding]:
    """Cada link interno de la copia debe resolver -- ni 404 ni error de servidor.

    Solo mira links internos (los que ya quedaron con clave relativa, ver
    qa/extract.py::_link_key): uno que sigue apuntando al sitio viejo lo
    reporta find_source_leaks, con un mensaje mas especifico.
    """
    findings: list[Finding] = []
    vistos: set[str] = set()

    for unit in copy_units:
        if unit.kind != "link" or not unit.key.startswith("/") or unit.key in vistos:
            continue
        vistos.add(unit.key)

        url = copy_site.rstrip("/") + unit.key
        status, _ = _check_url(url, session, cache)
        if status == 0:
            mensaje = f"Could not reach this link on the migrated site: {url}"
        elif status >= 400:
            mensaje = f"This link returns {status} on the migrated site: {url}"
        else:
            continue

        findings.append(Finding(
            verdict=Verdict.BROKEN_LINK,
            severity=Severity.ERROR,
            found=unit.text or unit.key,
            path=path,
            auto_fixable=False,
            message=mensaje,
            context=unit.describe(),
            meta={"url": url, "status": status},
        ))

    return findings


def check_link_destinations(pairs, source_site: str, copy_site: str, path: str,
                            session: requests.Session, cache: dict) -> list[Finding]:
    """El link cambia de URL entre plataformas, pero debe llevar al mismo lugar.

    pairs es la lista ya emparejada por qa.extract.pair_units (mismo texto de
    link entre original y copia, aunque el href sea distinto). Para cada par
    interno a su sitio, compara el titulo de la pagina de destino en los dos
    lados.
    """
    findings: list[Finding] = []
    vistos: set[tuple[str, str]] = set()

    for unit_copy, unit_source in pairs:
        if unit_copy.kind != "link" or unit_source.kind != "link":
            continue
        if not unit_copy.key.startswith("/") or not unit_source.key.startswith("/"):
            continue  # externo de un lado o del otro: no hay destino que comparar

        clave = (unit_copy.key, unit_source.key)
        if clave in vistos:
            continue
        vistos.add(clave)

        copy_url = copy_site.rstrip("/") + unit_copy.key
        copy_status, copy_title = _check_url(copy_url, session, cache)
        if copy_status == 0 or copy_status >= 400:
            continue  # ya lo reporta check_broken_links

        source_url = source_site.rstrip("/") + unit_source.key
        source_status, source_title = _check_url(source_url, session, cache)
        if source_status == 0 or source_status >= 400 or not source_title or not copy_title:
            continue  # sin titulo de los dos lados no hay con que comparar

        ratio = SequenceMatcher(None, source_title.lower(), copy_title.lower()).ratio()
        if ratio >= TITLE_MATCH_RATIO:
            continue

        findings.append(Finding(
            verdict=Verdict.LINK_MISMATCH,
            severity=Severity.WARNING,
            found=normalize_display(copy_title),
            expected=normalize_display(source_title),
            path=path,
            auto_fixable=False,
            message=(
                f"The link {unit_copy.text!r} leads to a page titled "
                f"{copy_title!r} on the migrated site, but the same link on "
                f"the source site leads to {source_title!r}. It may be "
                "pointing at the wrong section."
            ),
            context=unit_copy.describe(),
            meta={"copy_url": copy_url, "source_url": source_url, "ratio": round(ratio, 2)},
        ))

    return findings
