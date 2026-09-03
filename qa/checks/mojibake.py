"""Check: caracteres corruptos, acentos perdidos y typos del glosario.

Dos fuentes de reglas:

1. Generadas. El mojibake mas comun es UTF-8 leido como CP1252 (Ã¡ por á,
   â€™ por '). En vez de escribir esa tabla a mano -- que siempre queda
   incompleta -- se genera codificando cada caracter español y decodificandolo
   mal a proposito. Sale la tabla entera y sin olvidos.

2. Del CSV. char_rules.csv trae las que NO son UTF-8/CP1252: la corrupcion
   Û · Ì È Ò que ve el equipo, el replacement char, los acentos perdidos y
   los typos. Esas se mantienen editables por el equipo.

Igual que el check de entidades, esto corre sobre el TEXTO EXTRAIDO.
"""

import re

from qa.findings import Finding, Severity, Verdict

CONTEXT_CHARS = 40

# Caracteres que aparecen en contenido español de sitios de dealers.
# El   (espacio duro) va incluido: 'Â ' es de los mojibakes mas frecuentes.
_SOURCE_CHARS = "áéíóúñüÁÉÍÓÚÑÜ¿¡«»°ªº—–…€™©®“”‘’• "

_VERDICT_BY_TYPE = {
    "mojibake": Verdict.MOJIBAKE,
    "replacement_char": Verdict.LOST_CHAR,
    "lost_char": Verdict.LOST_CHAR,
    "typo": Verdict.OFF_GLOSSARY,
}

_SEVERITY = {
    "error": Severity.ERROR,
    "warning": Severity.WARNING,
    "info": Severity.INFO,
}


def build_utf8_cp1252_map() -> dict[str, str]:
    """Genera la tabla de mojibake UTF-8 -> CP1252 para los caracteres español."""
    mapping: dict[str, str] = {}
    for char in _SOURCE_CHARS:
        try:
            broken = char.encode("utf-8").decode("cp1252")
        except UnicodeDecodeError:
            continue
        if broken != char:
            mapping[broken] = char
    return mapping


GENERATED_MOJIBAKE = build_utf8_cp1252_map()


def _context(text: str, start: int, end: int) -> str:
    left = max(0, start - CONTEXT_CHARS)
    right = min(len(text), end + CONTEXT_CHARS)
    prefix = "..." if left > 0 else ""
    suffix = "..." if right < len(text) else ""
    return f"{prefix}{text[left:right]}{suffix}"


def _finding(verdict, severity, found, expected, path, text, start, end,
             message, auto_fixable, origin):
    return Finding(
        verdict=verdict,
        severity=severity,
        found=found,
        expected=expected,
        path=path,
        auto_fixable=auto_fixable,
        fixed=expected if auto_fixable else "",
        message=message,
        context=_context(text, start, end),
        meta={"origin": origin},
    )


def find_char_issues(text: str, char_rules=None, path: str = "") -> list[Finding]:
    """Busca mojibake, caracteres perdidos y typos en el texto extraido."""
    if not text:
        return []

    findings: list[Finding] = []
    covered: list[tuple[int, int]] = []

    def claim(start: int, end: int) -> bool:
        """Reserva un tramo del texto. False si ya lo tomo una regla mas larga."""
        if any(start < c_end and c_start < end for c_start, c_end in covered):
            return False
        covered.append((start, end))
        return True

    # 1. Mojibake generado. Patrones largos primero: 'Ã¡' antes que 'Ã'.
    for broken in sorted(GENERATED_MOJIBAKE, key=len, reverse=True):
        correct = GENERATED_MOJIBAKE[broken]
        for match in re.finditer(re.escape(broken), text):
            if not claim(match.start(), match.end()):
                continue
            findings.append(
                _finding(
                    Verdict.MOJIBAKE, Severity.ERROR, broken, correct, path,
                    text, match.start(), match.end(),
                    f"UTF-8/CP1252 mojibake: {broken!r} should be {correct!r}.",
                    True, "generada",
                )
            )

    # 2. Reglas del CSV que mantiene el equipo
    for rule in sorted(char_rules or [], key=lambda r: len(r.pattern), reverse=True):
        # Estas dos familias las cubre otro check. Las filas siguen en el CSV
        # como referencia del equipo, pero aplicarlas aca las duplicaria.
        if rule.rule_type == "unit":
            continue  # qa/checks/units.py, que compara contra el valor EN
        if rule.rule_type == "html_entity":
            continue  # qa/checks/entities.py, que las detecta todas genericamente
        if rule.pattern in GENERATED_MOJIBAKE:
            continue  # ya cubierta por la tabla generada

        verdict = _VERDICT_BY_TYPE.get(rule.rule_type, Verdict.MOJIBAKE)
        severity = _SEVERITY.get(rule.severity, Severity.ERROR)

        for match in re.finditer(re.escape(rule.pattern), text):
            if not claim(match.start(), match.end()):
                continue

            if rule.auto_fixable and rule.replacement:
                message = f"{rule.pattern!r} should be {rule.replacement!r}."
            elif rule.notes:
                message = f"{rule.pattern!r} needs human review. {rule.notes}"
            else:
                message = f"{rule.pattern!r} needs human review."

            findings.append(
                _finding(
                    verdict, severity, rule.pattern, rule.replacement, path,
                    text, match.start(), match.end(),
                    message, rule.auto_fixable and bool(rule.replacement), "csv",
                )
            )

    return findings


def fix_char_issues(text: str, char_rules=None) -> str:
    """Aplica solo las correcciones seguras. Lo no auto-corregible queda igual."""
    for broken in sorted(GENERATED_MOJIBAKE, key=len, reverse=True):
        text = text.replace(broken, GENERATED_MOJIBAKE[broken])

    for rule in sorted(char_rules or [], key=lambda r: len(r.pattern), reverse=True):
        if rule.rule_type == "unit" or not rule.auto_fixable or not rule.replacement:
            continue
        text = text.replace(rule.pattern, rule.replacement)

    return text
