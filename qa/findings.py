"""Modelo de hallazgos del QA."""

from dataclasses import dataclass, field
from enum import Enum


class Severity(str, Enum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class Verdict(str, Enum):
    # Check 1 — labels rotos
    BROKEN_KEY = "broken_key"
    BROKEN_KEY_SOURCE = "broken_key_source"
    HTML_ENTITY = "html_entity"
    MOJIBAKE = "mojibake"
    LOST_CHAR = "lost_char"
    # Check 2 — traducción contra glosario
    OFF_GLOSSARY = "off_glossary"
    NEAR_MISS = "near_miss"
    ACCEPTED_VARIANT = "accepted_variant"
    UNKNOWN_TERM = "unknown_term"
    PROPER_NOUN_ALTERED = "proper_noun_altered"
    DUPLICATE_TERM = "duplicate_term"
    CASE_MISMATCH = "case_mismatch"
    # Check 3 — contenido migrado
    UNTRANSLATED = "untranslated"
    MISSING = "missing"
    LOCALE_NOT_APPLIED = "locale_not_applied"
    POPUP_MISSING = "popup_missing"
    POPUP_EXTRA = "popup_extra"
    POPUP_BROKEN = "popup_broken"
    POPUP_BROKEN_SOURCE = "popup_broken_source"
    POPUP_UNVERIFIED = "popup_unverified"
    # Unidades
    UNIT_NOT_CONVERTED = "unit_not_converted"
    UNIT_MISLABELED = "unit_mislabeled"
    UNIT_UNVERIFIABLE = "unit_unverifiable"
    # Stare and Compare: sitio original contra sitio migrado
    TEXT_CHANGED = "text_changed"
    CONTENT_MISSING = "content_missing"
    CONTENT_EXTRA = "content_extra"
    SOURCE_LEAK = "source_leak"
    COUNT_MISMATCH = "count_mismatch"
    BROKEN_LINK = "broken_link"
    LINK_MISMATCH = "link_mismatch"
    # Estilo
    STYLE_VIOLATION = "style_violation"
    OK = "ok"


@dataclass
class Finding:
    verdict: Verdict
    severity: Severity
    found: str
    expected: str = ""
    path: str = ""
    auto_fixable: bool = False
    fixed: str = ""
    message: str = ""
    context: str = ""
    meta: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "verdict": self.verdict.value,
            "severity": self.severity.value,
            "found": self.found,
            "expected": self.expected,
            "path": self.path,
            "auto_fixable": self.auto_fixable,
            "fixed": self.fixed,
            "message": self.message,
            "context": self.context,
            "meta": self.meta,
        }
