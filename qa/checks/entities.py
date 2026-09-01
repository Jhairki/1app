"""Check: entidades HTML visibles como texto literal.

Una entidad como &#225; en el CÓDIGO FUENTE es correcta — se renderiza 'á'.
Solo es bug cuando el usuario la ve escrita en la página, que pasa con doble
escapado (&amp;#225; en el fuente).

Por eso este check corre sobre el TEXTO EXTRAÍDO (get_text()), nunca sobre el
HTML crudo: get_text() ya decodifica las entidades bien formadas, así que lo
que sobreviva ahí es exactamente el bug.
"""

import html
import re

from qa.findings import Finding, Severity, Verdict

# &#225;  |  &#xE1;  |  &aacute;
ENTITY_PATTERN = re.compile(r"&(?:#\d{1,7}|#[xX][0-9a-fA-F]{1,6}|[a-zA-Z][a-zA-Z0-9]{1,31});")

CONTEXT_CHARS = 40


def _context(text: str, start: int, end: int) -> str:
    left = max(0, start - CONTEXT_CHARS)
    right = min(len(text), end + CONTEXT_CHARS)
    prefix = "…" if left > 0 else ""
    suffix = "…" if right < len(text) else ""
    return f"{prefix}{text[left:right]}{suffix}"


def find_html_entities(text: str, path: str = "") -> list[Finding]:
    """Devuelve un hallazgo por cada entidad HTML visible como texto literal."""
    findings: list[Finding] = []
    seen: set[str] = set()

    for match in ENTITY_PATTERN.finditer(text):
        raw = match.group(0)
        decoded = html.unescape(raw)

        # html.unescape devuelve la cadena intacta si no es una entidad real
        # (p.ej. "&foo;"). Eso no es un bug de codificación, es texto normal.
        if decoded == raw:
            continue

        if raw in seen:
            continue
        seen.add(raw)

        findings.append(
            Finding(
                verdict=Verdict.HTML_ENTITY,
                severity=Severity.ERROR,
                found=raw,
                expected=decoded,
                path=path,
                auto_fixable=True,
                fixed=decoded,
                message=f"Entidad HTML visible como texto: {raw} debe mostrarse como {decoded}",
                context=_context(text, match.start(), match.end()),
            )
        )

    return findings


def fix_html_entities(text: str) -> str:
    """Aplica la corrección: reemplaza cada entidad literal por su carácter."""
    def _replace(match: re.Match) -> str:
        raw = match.group(0)
        decoded = html.unescape(raw)
        return decoded if decoded != raw else raw

    return ENTITY_PATTERN.sub(_replace, text)
