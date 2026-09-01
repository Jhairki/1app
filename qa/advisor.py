"""Capa de IA: propone, nunca juzga.

GARANTIAS (verificadas por tests/test_ai_no_perjudica.py):

  1. El asesor solo escribe en Finding.meta. Ningun otro campo se toca.
     verdict, severity, found, expected, auto_fixable y fixed quedan intactos.
  2. No borra ni agrega hallazgos. La lista que entra es la que sale.
  3. Solo mira los unknown_term: los casos donde el glosario NO tiene opinion.
     Un hallazgo determinista jamas pasa por el modelo.
  4. Si el modelo no esta, tarda o responde basura, el reporte sale identico
     al de un escaneo sin IA.
  5. El veredicto de aprobado/rechazado (los errores) nunca depende del modelo.

El rol del modelo es hacerse innecesario: cada termino que propone y un humano
aprueba se vuelve una fila del glosario, y a partir de ahi el check es
determinista para siempre.
"""

import logging
from dataclasses import dataclass, field

from qa.findings import Finding, Verdict
from qa.llm import LocalModel

logger = logging.getLogger(__name__)

# Unico veredicto que el modelo puede comentar: aquel donde lo determinista
# ya dijo todo lo que podia decir ("esto no esta en el glosario").
ADVISABLE = {Verdict.UNKNOWN_TERM}

# Tope de llamadas por escaneo, para que un sitio grande no dispare cientos
MAX_CALLS = 40

SYSTEM = (
    "Eres un traductor especializado en sitios web de concesionarios de autos "
    "en Estados Unidos. Traduces del ingles al español para el mercado "
    "hispanohablante de EE.UU. Usas millas, no kilometros. Respondes SOLO con "
    "JSON valido, sin markdown ni explicaciones fuera del JSON."
)

PROMPT_CON_INGLES = """Texto en la pagina en español: "{spanish}"
Texto equivalente en la pagina en ingles: "{english}"
Donde aparece: {context}

Responde con este JSON exacto:
{{"correcta": true o false,
  "sugerencia": "la traduccion que deberia usarse",
  "confianza": "alta" o "media" o "baja",
  "razon": "una frase corta en español"}}"""

PROMPT_SIN_INGLES = """Texto en la pagina en español: "{spanish}"
Donde aparece: {context}
No hay texto equivalente en ingles para comparar.

Evalua solo si es español correcto y natural para un sitio de concesionario.

Responde con este JSON exacto:
{{"correcta": true o false,
  "sugerencia": "como deberia escribirse",
  "confianza": "alta" o "media" o "baja",
  "razon": "una frase corta en español"}}"""

PROMPT_PENDIENTE = """Termino en ingles de un sitio de concesionario: "{english}"
{note}

Responde con este JSON exacto:
{{"sugerencia": "la traduccion al español",
  "confianza": "alta" o "media" o "baja",
  "razon": "una frase corta en español"}}"""


@dataclass
class Suggestion:
    """Opinion del modelo. Nunca es un veredicto de QA."""
    spanish: str
    english: str = ""
    looks_correct: bool = True
    proposal: str = ""
    confidence: str = "baja"
    reason: str = ""
    source: str = "modelo local"

    def as_dict(self) -> dict:
        return {
            "spanish": self.spanish,
            "english": self.english,
            "looks_correct": self.looks_correct,
            "proposal": self.proposal,
            "confidence": self.confidence,
            "reason": self.reason,
            "source": self.source,
        }


@dataclass
class AdvisorReport:
    ran: bool = False
    reason: str = ""
    calls: int = 0
    suggestions: list[Suggestion] = field(default_factory=list)
    candidates: list[dict] = field(default_factory=list)


def fingerprint(finding: Finding) -> tuple:
    """Los campos que deciden el QA. El asesor no puede cambiar ninguno."""
    return (
        finding.verdict,
        finding.severity,
        finding.found,
        finding.expected,
        finding.auto_fixable,
        finding.fixed,
        finding.message,
        finding.path,
    )


def _clean(value, fallback: str = "") -> str:
    return str(value).strip() if isinstance(value, (str, int, float)) else fallback


def _parse(data: dict, spanish: str, english: str):
    if not isinstance(data, dict):
        return None
    proposal = _clean(data.get("sugerencia"))
    confidence = _clean(data.get("confianza"), "baja").lower()
    if confidence not in {"alta", "media", "baja"}:
        confidence = "baja"
    return Suggestion(
        spanish=spanish,
        english=english,
        looks_correct=bool(data.get("correcta", True)),
        proposal=proposal,
        confidence=confidence,
        reason=_clean(data.get("razon")),
    )


def advise(findings: list[Finding], model: LocalModel = None,
           max_calls: int = MAX_CALLS) -> AdvisorReport:
    """Anota sugerencias en los unknown_term. Devuelve que hizo.

    La lista de findings se devuelve tal cual: esta funcion solo escribe en
    el diccionario meta de cada hallazgo elegible.
    """
    report = AdvisorReport()
    model = model or LocalModel()

    # LocalModel ya es a prueba de fallos, pero la garantia no puede depender
    # de que el modelo se porte bien: cualquier implementacion debe poder
    # explotar sin arrastrar al QA.
    try:
        disponible = model.available()
    except Exception as exc:
        logger.warning("El modelo fallo al verificar disponibilidad: %s", exc)
        report.reason = f"El modelo local fallo: {exc}"
        return report

    if not disponible:
        try:
            report.reason = model.status().get("reason", "")
        except Exception:
            report.reason = ""
        report.reason = report.reason or "El modelo local no esta disponible"
        return report

    report.ran = True
    cache: dict[tuple[str, str], Suggestion] = {}

    for finding in findings:
        if finding.verdict not in ADVISABLE:
            continue
        if report.calls >= max_calls:
            report.reason = f"Se alcanzo el tope de {max_calls} consultas al modelo."
            break

        spanish = finding.found
        english = finding.expected  # en unknown_term suele venir vacio
        key = (spanish, english)

        if key in cache:
            suggestion = cache[key]
        else:
            template = PROMPT_CON_INGLES if english else PROMPT_SIN_INGLES
            prompt = template.format(
                spanish=spanish, english=english, context=finding.context or "sin contexto"
            )
            report.calls += 1
            try:
                data = model.complete_json(prompt, system=SYSTEM)
            except Exception as exc:
                logger.warning("El modelo fallo consultando %r: %s", spanish, exc)
                report.reason = f"El modelo local fallo durante el escaneo: {exc}"
                break

            suggestion = _parse(data, spanish, english) if data else None
            if suggestion is None:
                continue
            cache[key] = suggestion
            report.suggestions.append(suggestion)

        # UNICO campo que este modulo escribe en un Finding
        finding.meta["ai_suggestion"] = suggestion.as_dict()

    report.candidates = build_candidates(report.suggestions)
    return report


def suggest_pending(glossary, model: LocalModel = None) -> list[Suggestion]:
    """Propone traduccion para los terminos marcados como pending."""
    model = model or LocalModel()
    try:
        if not model.available():
            return []
    except Exception:
        return []

    suggestions: list[Suggestion] = []
    for entry in glossary.pending:
        note = f"Nota del glosario: {entry.notes}" if entry.notes else ""
        try:
            data = model.complete_json(
                PROMPT_PENDIENTE.format(english=entry.english, note=note), system=SYSTEM
            )
        except Exception as exc:
            logger.warning("El modelo fallo con el pendiente %r: %s", entry.english, exc)
            break
        parsed = _parse(data, spanish="", english=entry.english) if data else None
        if parsed and parsed.proposal:
            suggestions.append(parsed)
    return suggestions


def build_candidates(suggestions: list[Suggestion]) -> list[dict]:
    """Filas listas para pegar en glossary.csv, para que un humano las revise."""
    candidates = []
    seen: set[str] = set()
    for suggestion in suggestions:
        english = suggestion.english or suggestion.proposal
        if not english or english in seen:
            continue
        seen.add(english)
        candidates.append({
            "english": english,
            "spanish_canonical": suggestion.proposal or suggestion.spanish,
            "spanish_accepted": "",
            "policy": "translate",
            "context": "",
            "notes": f"propuesto por IA ({suggestion.confidence}) - REVISAR",
        })
    return candidates
