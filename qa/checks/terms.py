"""Checks 2 y 3: traducción contra el glosario, y contenido sin traducir.

Este es el modulo donde el glosario deja de ser una tabla de consulta y pasa a
emitir el veredicto. Cada texto de la pagina española sale clasificado, no solo
los que ya venian rotos.

Dos modos de operacion:

  Emparejado   - tenemos el texto EN del mismo elemento (mismo href/posicion).
                 Es el modo fuerte: sabemos que termino se ESPERABA ahi.
  Sin emparejar- solo tenemos el texto ES. Alcanza para detectar ingles sin
                 traducir y traducciones fuera de glosario, pero no para saber
                 que se esperaba cuando el termino no esta en el glosario.
"""

import re
from difflib import SequenceMatcher

from qa.casing import apply_case_style, case_compatible, case_style, describe
from qa.findings import Finding, Severity, Verdict
from qa.glossary import Entry, Glossary, Policy
from qa.normalize import differs_only_by_accent, normalize, normalize_display

# Arriba de esto, dos textos distintos se consideran "casi el mismo".
# Aplica cuando SI sabemos que termino se esperaba, por el par en ingles.
NEAR_MISS_RATIO = 0.85

# Cuando NO hay par en ingles hay que adivinar contra que entrada comparar, y
# adivinar mal cuesta caro: en un sitio real 'Vehiculos Usados Certificados'
# (que es correcto) se parecia 90% a 'Vehiculos Usados Clasificados' y salia
# reportado 33 veces. Sin par, el parecido tiene que ser casi total.
GUESS_RATIO = 0.94

# Solo cuentan como letras y digitos, para comparar nombres propios
SOLO_ALFANUM = re.compile(r"[^0-9a-záéíóúüñ]+", re.IGNORECASE)

PLACEHOLDER = re.compile(r"\{(\w+)\}")


def build_pattern_regex(template: str) -> re.Pattern:
    """Convierte 'View {n} Qualifying Vehicle(s)' en un regex con grupo n."""
    parts = []
    last = 0
    for match in PLACEHOLDER.finditer(template):
        parts.append(re.escape(template[last:match.start()]))
        parts.append(f"(?P<{match.group(1)}>.+?)")
        last = match.end()
    parts.append(re.escape(template[last:]))
    return re.compile("^" + "".join(parts) + "$", re.IGNORECASE)


def similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


class TermChecker:
    """Emite un veredicto por cada texto encontrado en la pagina española."""

    def __init__(self, glossary: Glossary):
        self.glossary = glossary
        self.patterns = [
            (entry, build_pattern_regex(normalize(entry.english)),
             build_pattern_regex(normalize(entry.spanish_canonical)))
            for entry in glossary.patterns
        ]
        # Solo los que DEBEN traducirse cuentan como "ingles sin traducir".
        # CarFinder, Recall y Detailing aparecen en ingles a proposito.
        self.translatable_english = {
            normalize(e.english): e
            for e in glossary.entries
            if e.policy is Policy.TRANSLATE and e.spanish_canonical
        }

    # ---------- helpers ----------

    def _match_pattern(self, text: str):
        """Devuelve (entry, lado) si el texto encaja en alguna plantilla."""
        normalized = normalize(text)
        for entry, english_re, spanish_re in self.patterns:
            if spanish_re.match(normalized):
                return entry, "spanish"
            if english_re.match(normalized):
                return entry, "english"
        return None

    @staticmethod
    def _cased(expected: str, english_text: str) -> str:
        """Ajusta la correccion sugerida al patron de mayusculas del ingles.

        Si el ingles dice ALL INVENTORY, la correccion no puede ser
        'Todos los Vehiculos' sino 'TODOS LOS VEHICULOS'.
        """
        if not english_text or not expected:
            return expected
        # Solo se reescribe cuando la transformacion es inequivoca. En Title y
        # Sentence case la canonica ya la escribio un humano ("Valore Su
        # Vehiculo"): reformatearla le cambiaria las mayusculas a mano.
        style = case_style(english_text)
        if style not in ("upper", "lower"):
            return expected
        return apply_case_style(expected, style)

    def _case_finding(self, entry: Entry, spanish_text: str, english_text: str,
                      shown: str, path: str):
        """Hallazgo si el español no respeta las mayusculas del ingles."""
        if not english_text or case_compatible(english_text, spanish_text):
            return None

        corrected = apply_case_style(shown, case_style(english_text))
        return Finding(
            verdict=Verdict.CASE_MISMATCH,
            severity=Severity.ERROR,
            found=shown,
            expected=corrected,
            path=path,
            auto_fixable=True,
            fixed=corrected,
            message=(
                f"The term is right but the capitalization does not follow English: "
                f"{english_text!r} is {describe(case_style(english_text))} while the "
                f"page uses {describe(case_style(spanish_text))}."
            ),
            context=entry.context,
            meta={
                "english_style": case_style(english_text),
                "spanish_style": case_style(spanish_text),
            },
        )

    def _closest_entry(self, normalized: str):
        """Entrada del glosario cuya traducción mas se parece al texto dado."""
        best, best_ratio = None, 0.0
        for entry in self.glossary.entries:
            for candidate in entry.all_spanish():
                ratio = similarity(normalized, normalize(candidate))
                if ratio > best_ratio:
                    best, best_ratio = entry, ratio
        return best, best_ratio

    # ---------- veredicto ----------

    def check(self, spanish_text: str, english_text: str = "", path: str = "") -> Finding:
        shown = normalize_display(spanish_text)
        normalized = normalize(spanish_text)

        if not normalized:
            return Finding(Verdict.OK, Severity.INFO, shown, path=path)

        expected_entry = self.glossary.lookup_english(english_text) if english_text else None

        # --- Check 3: ingles sin traducir en la pagina española ---
        untranslated = self.translatable_english.get(normalized)
        if untranslated is not None:
            # El texto ES esta en ingles, asi que su propio casing es la referencia
            expected = self._cased(untranslated.spanish_canonical, spanish_text)
            return Finding(
                verdict=Verdict.UNTRANSLATED,
                severity=Severity.ERROR,
                found=shown,
                expected=expected,
                path=path,
                auto_fixable=True,
                fixed=expected,
                message=(
                    f"The text is still in English on the Spanish page. "
                    f"It should read {expected!r}."
                ),
                context=untranslated.context,
            )

        # --- Plantillas ({n}, {year}) ---
        pattern_hit = self._match_pattern(spanish_text)
        if pattern_hit is not None:
            entry, side = pattern_hit
            if side == "spanish":
                return Finding(Verdict.OK, Severity.INFO, shown, path=path, context=entry.context)
            return Finding(
                verdict=Verdict.UNTRANSLATED,
                severity=Severity.ERROR,
                found=shown,
                expected=entry.spanish_canonical,
                path=path,
                message=(
                    f"Matches the English template {entry.english!r}; it should follow "
                    f"the Spanish one {entry.spanish_canonical!r}."
                ),
                context=entry.context,
            )

        # --- Check 2: el español encontrado contra el glosario ---
        spanish_hit = self.glossary.lookup_spanish(spanish_text)
        if spanish_hit is not None:
            entry, kind = spanish_hit

            # Estaba bien traducido, pero no es el termino que tocaba aqui.
            # Se comparan las traducciones, no las entradas: 'Trade-In Appraisal'
            # y 'Value Your Trade' comparten canonica y no deben chocar.
            same_translation = (
                expected_entry is not None
                and normalize(entry.spanish_canonical)
                == normalize(expected_entry.spanish_canonical)
            )
            if expected_entry is not None and entry is not expected_entry and not same_translation:
                corrected = self._cased(expected_entry.spanish_canonical, english_text)
                return Finding(
                    verdict=Verdict.OFF_GLOSSARY,
                    severity=Severity.ERROR,
                    found=shown,
                    expected=corrected,
                    path=path,
                    auto_fixable=True,
                    fixed=corrected,
                    message=(
                        f"English said {expected_entry.english!r}, which translates to "
                        f"{expected_entry.spanish_canonical!r}, but the page uses the "
                        f"translation of {entry.english!r}."
                    ),
                    context=expected_entry.context,
                )

            # El termino es el correcto: ahora si, las mayusculas
            case_issue = self._case_finding(entry, spanish_text, english_text, shown, path)
            if case_issue is not None:
                return case_issue

            if kind == "accepted":
                return Finding(
                    verdict=Verdict.ACCEPTED_VARIANT,
                    severity=Severity.INFO,
                    found=shown,
                    expected=entry.spanish_canonical,
                    path=path,
                    message=(
                        f"Accepted variant. The official one is {entry.spanish_canonical!r}."
                    ),
                    context=entry.context,
                )

            return Finding(Verdict.OK, Severity.INFO, shown, path=path, context=entry.context)

        # --- No matcheo nada. Que tan cerca esta de lo que se esperaba? ---
        if expected_entry is not None and expected_entry.spanish_canonical:
            return self._verdict_against(expected_entry, normalized, shown, path, english_text)

        entry, ratio = self._closest_entry(normalized)
        if entry is not None and ratio >= GUESS_RATIO:
            return self._verdict_against(entry, normalized, shown, path, english_text)

        # Fuera del glosario, pero con par EN: si los dos textos son casi
        # iguales, es un nombre propio (modelo, marca) que se altero al migrar.
        # 'Sierra 2500 HD' -> 'Sierra 2500HD' no es una traduccion, es un error.
        if english_text:
            english_shown = normalize_display(english_text)
            # El criterio NO puede ser "se parecen": español e ingles comparten
            # raices latinas y 'Contacto'/'Contact' dan 93% siendo una
            # traduccion correcta. El criterio es que sean la MISMA cadena al
            # quitar espacios y puntuacion: 'Silverado 2500HD' contra
            # 'Silverado 2500 HD' es el mismo nombre escrito distinto.
            solo_es = SOLO_ALFANUM.sub("", normalized)
            solo_en = SOLO_ALFANUM.sub("", normalize(english_text))
            if normalized != normalize(english_text) and solo_es and solo_es == solo_en:
                return Finding(
                    verdict=Verdict.PROPER_NOUN_ALTERED,
                    severity=Severity.WARNING,
                    found=shown,
                    expected=english_shown,
                    path=path,
                    auto_fixable=False,
                    fixed=english_shown,
                    message=(
                        "Same name spelled differently across languages (spacing or "
                        "punctuation). Model names are copied verbatim."
                    ),
                )

        return Finding(
            verdict=Verdict.UNKNOWN_TERM,
            severity=Severity.INFO,
            found=shown,
            path=path,
            message="Not in the glossary. Candidate to add.",
        )

    def _verdict_against(self, entry: Entry, normalized: str, shown: str, path: str,
                         english_text: str = "") -> Finding:
        """Clasifica un texto que no matcheo exacto contra la entrada esperada."""
        canonical = self._cased(entry.spanish_canonical, english_text)

        if differs_only_by_accent(normalized, normalize(canonical)):
            return Finding(
                verdict=Verdict.NEAR_MISS,
                severity=Severity.ERROR,
                found=shown,
                expected=canonical,
                path=path,
                auto_fixable=True,
                fixed=canonical,
                message=f"Differs from {canonical!r} only in the accents.",
                context=entry.context,
                meta={"reason": "accent"},
            )

        ratio = similarity(normalized, normalize(canonical))
        if ratio >= NEAR_MISS_RATIO:
            return Finding(
                verdict=Verdict.NEAR_MISS,
                severity=Severity.WARNING,
                found=shown,
                expected=canonical,
                path=path,
                auto_fixable=False,
                fixed=canonical,
                message=f"Very close to {canonical!r} ({ratio:.0%}), but not the same.",
                context=entry.context,
                meta={"reason": "similar", "ratio": round(ratio, 3)},
            )

        return Finding(
            verdict=Verdict.OFF_GLOSSARY,
            severity=Severity.ERROR,
            found=shown,
            expected=canonical,
            path=path,
            auto_fixable=True,
            fixed=canonical,
            message=(
                f"Translation outside the glossary. For {entry.english!r} the "
                f"official one is {canonical!r}."
            ),
            context=entry.context,
            meta={"ratio": round(ratio, 3)},
        )


def check_terms(glossary: Glossary, pairs, path: str = "") -> list[Finding]:
    """Corre el check sobre una lista de (texto_es, texto_en) de una pagina."""
    checker = TermChecker(glossary)
    return [checker.check(es, en or "", path) for es, en in pairs]
