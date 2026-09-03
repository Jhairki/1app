"""Descarga de paginas con locale.

El sitio cambia de idioma por query param: ?locale=es_US / ?locale=en_US.
Todo lo relacionado con construir esas URLs vive aca.
"""

import logging
import time
from urllib.parse import parse_qs, urlencode, urljoin, urlparse, urlunparse

import requests

logger = logging.getLogger(__name__)

SPANISH = "es_US"
ENGLISH = "en_US"

# En este CMS toda seccion se referencia como carpeta/index.htm
# (/showroom/index.htm, /new-inventory/index.htm...). El link del logo del
# sitio apunta a "/" a secas, asi que sin esto la portada quedaba con una
# pinta distinta al resto de las paginas en el reporte. Verificado que
# /index.htm resuelve igual que "/" en el CMS.
HOME_PATH = "/index.htm"


def normalize_home_path(path: str) -> str:
    """La portada como '/index.htm', igual que las demas secciones del sitio."""
    return HOME_PATH if path in ("", "/") else path

REQUEST_DELAY_SECONDS = 1.0
REQUEST_TIMEOUT_SECONDS = 30
USER_AGENT = "LocaleQABot/2.0"

# Muchos sitios sirven HTML distinto a un movil. Para que el Field 1 del
# reporte diga M con fundamento, hay que pedir la pagina como pide un movil,
# no solo etiquetar el reporte.
MOBILE_USER_AGENT = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 "
    "Safari/604.1 LocaleQABot/2.0"
)


def normalize_base_url(url: str) -> str:
    url = (url or "").strip()
    if not url:
        raise ValueError("Hace falta la URL base del sitio.")
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    if not url.endswith("/"):
        url += "/"
    return url


def with_locale(base_url: str, relative_path: str, locale: str) -> str:
    """Arma la URL absoluta de un path con el locale pedido."""
    absolute = urljoin(base_url, relative_path)
    parsed = urlparse(absolute)
    query = parse_qs(parsed.query, keep_blank_values=True)
    query["locale"] = [locale]
    return urlunparse(parsed._replace(query=urlencode(query, doseq=True)))


def strip_locale(url: str) -> str:
    """Quita el parametro locale. Sirve para emparejar links ES con sus EN."""
    parsed = urlparse(url)
    query = parse_qs(parsed.query, keep_blank_values=True)
    query.pop("locale", None)
    return urlunparse(parsed._replace(query=urlencode(query, doseq=True)))


def to_relative_path(base_url: str, href: str):
    """Normaliza un href a un path relativo del propio sitio. None si es externo."""
    if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
        return None
    absolute = urljoin(base_url, href)
    base = urlparse(base_url)
    link = urlparse(absolute)
    if link.netloc and link.netloc != base.netloc:
        return None
    path = link.path or "/"
    if not path.startswith("/"):
        path = "/" + path
    return path


def make_session(mobile: bool = False) -> requests.Session:
    session = requests.Session()
    session.headers.update({"User-Agent": MOBILE_USER_AGENT if mobile else USER_AGENT})
    return session


def fetch_html(session: requests.Session, url: str):
    """Devuelve el HTML, o None si la pagina no se pudo traer."""
    try:
        response = session.get(url, timeout=REQUEST_TIMEOUT_SECONDS)
        response.raise_for_status()
        # requests adivina mal el encoding cuando no viene en el header;
        # apparent_encoding lo detecta del contenido y evita mojibake propio.
        if response.encoding is None or response.encoding.lower() == "iso-8859-1":
            response.encoding = response.apparent_encoding
        return response.text
    except requests.RequestException as exc:
        logger.error("No se pudo traer %s: %s", url, exc)
        return None


def polite_pause() -> None:
    time.sleep(REQUEST_DELAY_SECONDS)
