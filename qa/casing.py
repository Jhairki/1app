"""Estilo de mayusculas: el español debe seguir el mismo patron que el ingles.

Ojo con el detalle del español: en Title Case los articulos y preposiciones van
en minuscula. El glosario ya esta escrito asi -- "Todos los Vehiculos",
"Centro de Reparacion de Choques", "De por Vida" -- asi que una comparacion
estricta palabra por palabra daria falsos positivos. Por eso las palabras
funcionales se ignoran al clasificar.
"""

import re

# Palabras que pueden ir en minuscula dentro de un titulo sin que deje de serlo
FUNCTION_WORDS = {
    # español
    "de", "del", "la", "las", "el", "los", "y", "e", "o", "u", "en", "a", "al",
    "por", "para", "con", "sin", "un", "una", "que", "su", "sus",
    # ingles
    "of", "the", "and", "or", "in", "on", "at", "to", "for", "with", "a", "an",
    "by", "from", "up",
}

WORD = re.compile(r"[^\W\d_]+", re.UNICODE)

UPPER = "upper"
LOWER = "lower"
TITLE = "title"
SENTENCE = "sentence"
CAPITALIZED = "capitalized"   # una sola palabra con inicial mayuscula
MIXED = "mixed"               # no se puede clasificar: sin opinion
NONE = "none"                 # sin letras

# Que estilo del español es aceptable para cada estilo del ingles
COMPATIBLE = {
    UPPER: {UPPER},
    LOWER: {LOWER},
    TITLE: {TITLE, CAPITALIZED},
    SENTENCE: {SENTENCE, CAPITALIZED},
    CAPITALIZED: {CAPITALIZED, TITLE, SENTENCE},
}

LABELS = {
    UPPER: "TODO EN MAYUSCULAS",
    LOWER: "todo en minusculas",
    TITLE: "Title Case",
    SENTENCE: "Sentence case",
    CAPITALIZED: "Inicial Mayuscula",
    MIXED: "mixto",
    NONE: "sin letras",
}


def _words(text: str) -> list[str]:
    return WORD.findall(text or "")


def case_style(text: str) -> str:
    """Clasifica el patron de mayusculas de un texto."""
    words = _words(text)
    if not words:
        return NONE

    letters = [c for c in text if c.isalpha()]
    if not letters:
        return NONE

    if all(c.isupper() for c in letters):
        # Una sola letra mayuscula no alcanza para afirmar "TODO MAYUSCULAS"
        return UPPER if len(letters) > 1 else CAPITALIZED
    if all(c.islower() for c in letters):
        return LOWER

    uppercase = sum(1 for c in letters if c.isupper())
    lowercase = len(letters) - uppercase

    # Mayoria de mayusculas con alguna minuscula suelta: la intencion era
    # TODO EN MAYUSCULAS y algun caracter quedo mal (VEHiCULOS CERTIFICADOS).
    if uppercase > lowercase:
        return UPPER

    # Palabras de marca con mayuscula interna (ePrice, CarFinder, iPhone) rompen
    # cualquier clasificacion. Se reconocen porque son mayoria minusculas; los
    # acronimos completos (KBB) ya quedaron descartados arriba.
    if any(any(c.isupper() for c in w[1:]) and not w.isupper() for w in words):
        return MIXED

    if len(words) == 1:
        return CAPITALIZED if words[0][0].isupper() else MIXED

    significant = [w for w in words if w.lower() not in FUNCTION_WORDS]
    if not significant:
        significant = words

    first_upper = words[0][0].isupper()

    if all(w[0].isupper() for w in significant) and first_upper:
        return TITLE

    if first_upper and all(w[0].islower() for w in words[1:]):
        return SENTENCE

    return MIXED


def case_compatible(english_text: str, spanish_text: str) -> bool:
    """True si el español respeta el patron de mayusculas del ingles."""
    english_style = case_style(english_text)
    spanish_style = case_style(spanish_text)

    # Sin opinion: no inventamos un hallazgo con evidencia debil
    if english_style in (MIXED, NONE) or spanish_style in (MIXED, NONE):
        return True

    return spanish_style in COMPATIBLE.get(english_style, {english_style})


def apply_case_style(text: str, style: str) -> str:
    """Reescribe un texto con el patron de mayusculas indicado."""
    if style == UPPER:
        return text.upper()
    if style == LOWER:
        return text.lower()
    if style == SENTENCE:
        lowered = text.lower()
        return lowered[:1].upper() + lowered[1:]
    if style in (TITLE, CAPITALIZED):
        def _fix(match: re.Match) -> str:
            word = match.group(0)
            if match.start() > 0 and word.lower() in FUNCTION_WORDS:
                return word.lower()
            return word[:1].upper() + word[1:].lower()

        return WORD.sub(_fix, text)
    return text


def describe(style: str) -> str:
    return LABELS.get(style, style)
