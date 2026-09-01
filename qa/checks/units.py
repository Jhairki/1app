"""Check: unidades de distancia entre la página EN y la ES.

Regla del equipo: si la página en español cambió la unidad a kilómetros pero
dejó el mismo número que la inglesa, el valor es FALSO — 45,000 miles no son
45,000 km. Eso es bug.

Si sí se hizo la conversión (el número cambió por el factor correcto), el
contenido cuadra y se mantiene.

Casos:
  ES "45,000 millas"    + EN "45,000 miles"  -> OK, solo se tradujo la palabra
  ES "45,000 kilómetros"+ EN "45,000 miles"  -> BUG unit_not_converted
  ES "72,420 kilómetros"+ EN "45,000 miles"  -> OK, conversión real
  ES "72,420 millas"    + EN "45,000 miles"  -> BUG unit_mislabeled
  ES con unidad, sin contraparte en EN       -> unit_unverifiable (informativo)
"""

import re

from qa.findings import Finding, Severity, Verdict

MILES_TO_KM = 1.609344
TOLERANCE = 0.02  # 2% — los sitios redondean

_KM_WORDS = {"km", "kms", "kilómetro", "kilómetros", "kilometro", "kilometros"}
_MILE_WORDS = {"mile", "miles", "milla", "millas"}

MEASUREMENT = re.compile(
    r"(?P<value>\d[\d.,\u00a0\s]*\d|\d)\s*"
    r"(?P<unit>kil[óo]metros?|kms?|millas?|miles?)\b",
    re.IGNORECASE,
)


def parse_number(raw: str) -> float | None:
    """Interpreta un número en formato EN (45,000.5) o ES (45.000,5)."""
    text = raw.replace("\u00a0", "").replace(" ", "").strip()
    if not text:
        return None

    has_comma = "," in text
    has_dot = "." in text

    if has_comma and has_dot:
        # El separador que aparece más a la derecha es el decimal
        decimal_sep = "," if text.rfind(",") > text.rfind(".") else "."
        thousands_sep = "." if decimal_sep == "," else ","
        text = text.replace(thousands_sep, "").replace(decimal_sep, ".")
    elif has_comma or has_dot:
        sep = "," if has_comma else "."
        parts = text.split(sep)
        # Un solo separador seguido de exactamente 3 dígitos -> millares
        if len(parts) > 2 or len(parts[-1]) == 3:
            text = text.replace(sep, "")
        else:
            text = text.replace(sep, ".")

    try:
        return float(text)
    except ValueError:
        return None


def _unit_kind(unit: str) -> str:
    lowered = unit.lower()
    if lowered in _KM_WORDS:
        return "km"
    if lowered in _MILE_WORDS:
        return "miles"
    return "unknown"


def extract_measurements(text: str) -> list[tuple[float, str, str]]:
    """Devuelve [(valor, tipo_de_unidad, texto_original), ...]."""
    results = []
    for match in MEASUREMENT.finditer(text or ""):
        value = parse_number(match.group("value"))
        kind = _unit_kind(match.group("unit"))
        if value is not None and kind != "unknown":
            results.append((value, kind, match.group(0)))
    return results


def _close(a: float, b: float) -> bool:
    if b == 0:
        return a == 0
    return abs(a - b) / abs(b) <= TOLERANCE


def check_units(spanish_text: str, english_text: str, path: str = "") -> list[Finding]:
    spanish = extract_measurements(spanish_text)
    english_miles = [v for v, kind, _ in extract_measurements(english_text) if kind == "miles"]

    findings: list[Finding] = []

    for value, kind, raw in spanish:
        same_as_english = next((m for m in english_miles if _close(value, m)), None)
        converted_from = next((m for m in english_miles if _close(value, m * MILES_TO_KM)), None)

        if kind == "km":
            if same_as_english is not None and converted_from is None:
                findings.append(
                    Finding(
                        verdict=Verdict.UNIT_NOT_CONVERTED,
                        severity=Severity.ERROR,
                        found=raw,
                        expected=f"{same_as_english * MILES_TO_KM:,.0f} kilómetros o {same_as_english:,.0f} millas",
                        path=path,
                        auto_fixable=False,
                        message=(
                            f"Se cambió la unidad a kilómetros pero el número quedó igual que en "
                            f"inglés ({same_as_english:,.0f} miles). El valor mostrado es incorrecto."
                        ),
                        meta={"english_value": same_as_english, "spanish_value": value},
                    )
                )
            elif converted_from is None:
                findings.append(
                    Finding(
                        verdict=Verdict.UNIT_UNVERIFIABLE,
                        severity=Severity.INFO,
                        found=raw,
                        path=path,
                        message="No se encontró el valor equivalente en la página en inglés para verificar la conversión.",
                        meta={"spanish_value": value},
                    )
                )

        elif kind == "miles":
            if converted_from is not None and same_as_english is None:
                findings.append(
                    Finding(
                        verdict=Verdict.UNIT_MISLABELED,
                        severity=Severity.ERROR,
                        found=raw,
                        expected=f"{converted_from:,.0f} millas",
                        path=path,
                        auto_fixable=False,
                        message=(
                            f"El número fue convertido a kilómetros ({value:,.0f}) pero la unidad "
                            f"dice millas. En inglés son {converted_from:,.0f} miles."
                        ),
                        meta={"english_value": converted_from, "spanish_value": value},
                    )
                )
            elif same_as_english is None and converted_from is None:
                findings.append(
                    Finding(
                        verdict=Verdict.UNIT_UNVERIFIABLE,
                        severity=Severity.INFO,
                        found=raw,
                        path=path,
                        message="No se encontró el valor equivalente en la página en inglés para verificar.",
                        meta={"spanish_value": value},
                    )
                )

    return findings
