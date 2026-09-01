"""Normalización de texto para comparar contra el glosario.

IMPORTANTE: esta normalización es SOLO para el match de términos.
Las reglas de carácter (mojibake, entidades) corren sobre el texto crudo
extraído, ANTES de normalizar — si no, se borrarían las señales que buscan.
"""

import re
import unicodedata

NBSP = "\u00a0"

_WHITESPACE = re.compile(r"\s+")

_QUOTE_MAP = {
    "\u2018": "'", "\u2019": "'", "\u201a": "'", "\u201b": "'",
    "\u201c": '"', "\u201d": '"', "\u201e": '"', "\u201f": '"',
    "\u00ab": '"', "\u00bb": '"',
}

_DASH_MAP = {
    "\u2010": "-", "\u2011": "-", "\u2012": "-",
    "\u2013": "-", "\u2014": "-", "\u2015": "-",
}

_TRANSLATION = str.maketrans({**_QUOTE_MAP, **_DASH_MAP, NBSP: " "})

_TRAILING_PUNCT = re.compile(r"[\s.,;:!¡?¿]+$")


def normalize(text: str) -> str:
    """Normaliza un texto para compararlo contra el glosario.

    Conserva los acentos a propósito: 'Vehiculos' sin tilde debe salir como
    hallazgo, no matchear en silencio con 'Vehículos'.
    """
    if not text:
        return ""
    text = unicodedata.normalize("NFC", text)
    text = text.translate(_TRANSLATION)
    text = _WHITESPACE.sub(" ", text).strip()
    text = _TRAILING_PUNCT.sub("", text)
    return text.casefold()


def normalize_display(text: str) -> str:
    """Igual que normalize() pero conserva mayúsculas — para mostrar en el reporte."""
    if not text:
        return ""
    text = unicodedata.normalize("NFC", text)
    text = text.translate(_TRANSLATION)
    return _WHITESPACE.sub(" ", text).strip()


def strip_accents(text: str) -> str:
    """Quita acentos. USO EXCLUSIVO: detectar el hallazgo 'falta una tilde'.

    Nunca usar para decidir si un término matchea — eso haría pasar
    'Vehiculos' como correcto.
    """
    decomposed = unicodedata.normalize("NFD", text)
    return "".join(c for c in decomposed if unicodedata.category(c) != "Mn")


def differs_only_by_accent(a: str, b: str) -> bool:
    """True si dos textos son idénticos salvo por los acentos."""
    if a == b:
        return False
    return strip_accents(a) == strip_accents(b)
