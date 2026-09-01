"""Check 1: claves internas del CMS que se escaparon a la pagina.

Cuando el CMS no resuelve un label, publica la clave cruda en vez del texto.
El caso tipico del equipo es SITEBUILDER_BUTTONBLOCK_*_LINKTEXT, pero el mismo
sintoma aparece con placeholders de plantilla sin renderizar y con valores de
codigo que se filtran ({{...}}, ${...}, undefined).

Este check no necesita el glosario: la clave cruda es un bug se traduzca o no.
"""

import re

from qa.findings import Finding, Severity, Verdict

CONTEXT_CHARS = 40

# (patron, descripcion). El orden importa: lo mas especifico primero.
KEY_PATTERNS = [
    (
        re.compile(r"\bSITEBUILDER_[A-Z0-9_]+\b", re.IGNORECASE),
        "clave interna de SiteBuilder",
    ),
    (
        re.compile(r"\{\{[^{}]{1,80}\}\}"),
        "placeholder de plantilla sin resolver",
    ),
    (
        re.compile(r"\$\{[^{}]{1,80}\}"),
        "placeholder de plantilla sin resolver",
    ),
    (
        re.compile(r"\[\[[^\[\]]{1,80}\]\]"),
        "placeholder sin resolver",
    ),
    (
        re.compile(r"%%[^%]{1,80}%%"),
        "placeholder sin resolver",
    ),
    (
        # Al menos tres segmentos: FOO_BAR_BAZ. Evita marcar siglas sueltas.
        re.compile(r"\b[A-Z][A-Z0-9]*(?:_[A-Z0-9]+){2,}\b"),
        "clave en mayusculas con guiones bajos",
    ),
    (
        re.compile(r"\b(?:undefined|null|NaN)\b"),
        "valor de codigo visible en la pagina",
    ),
]

# Un label completo que es solo mayusculas, digitos, guiones y underscores
WHOLE_LABEL_KEY = re.compile(r"^[A-Z0-9_\-]{9,}$")


def _context(text: str, start: int, end: int) -> str:
    left = max(0, start - CONTEXT_CHARS)
    right = min(len(text), end + CONTEXT_CHARS)
    prefix = "..." if left > 0 else ""
    suffix = "..." if right < len(text) else ""
    return f"{prefix}{text[left:right]}{suffix}"


def keys_in(text: str) -> set[str]:
    """Las claves crudas presentes en un texto, sin armar hallazgos."""
    return {f.found for f in find_broken_keys(text)}


def _finding(hit: str, path: str, context: str, base_message: str,
             english_keys: set[str]) -> Finding:
    """Arma el hallazgo, marcando si la clave tambien esta en ingles."""
    if hit in english_keys:
        return Finding(
            verdict=Verdict.BROKEN_KEY_SOURCE,
            severity=Severity.WARNING,
            found=hit,
            path=path,
            auto_fixable=False,
            message=(
                f"{base_message} Tambien aparece en la pagina en INGLES, asi que "
                "el label nunca se lleno en el CMS. No es un bug de traduccion."
            ),
            context=context,
            meta={"in_english_too": True},
        )
    return Finding(
        verdict=Verdict.BROKEN_KEY,
        severity=Severity.ERROR,
        found=hit,
        path=path,
        auto_fixable=False,
        message=base_message,
        context=context,
        meta={"in_english_too": False},
    )


def find_broken_keys(text: str, path: str = "",
                     english_keys: set[str] | None = None) -> list[Finding]:
    """Devuelve un hallazgo por cada clave cruda visible en el texto.

    Si se pasan las claves de la pagina inglesa, se distingue de quien es el bug:

      solo en español  -> el label ingles existe y el español no se lleno.
                          Es un bug de localizacion, del equipo de traduccion.
      en los dos       -> el label nunca se lleno en ningun idioma. Es un bug
                          de contenido del CMS, no de la traduccion.
    """
    if not text:
        return []

    english_keys = english_keys or set()
    findings: list[Finding] = []
    seen: set[str] = set()

    stripped = text.strip()
    if WHOLE_LABEL_KEY.match(stripped):
        seen.add(stripped)
        findings.append(_finding(stripped, path, stripped,
                                 "El label completo es una clave interna, no texto para el usuario.",
                                 english_keys))

    for pattern, description in KEY_PATTERNS:
        for match in pattern.finditer(text):
            hit = match.group(0)
            if hit in seen:
                continue
            seen.add(hit)
            findings.append(_finding(
                hit, path, _context(text, match.start(), match.end()),
                f"{description}: {hit!r} no deberia ser visible.", english_keys))

    return findings


def is_broken_key(text: str) -> bool:
    """True si el texto contiene alguna clave cruda. Util para filtrar antes
    de correr el check de glosario: una clave rota no es una mala traduccion."""
    return bool(find_broken_keys(text))
