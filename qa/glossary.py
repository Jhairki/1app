"""Carga y validación del glosario, las reglas de carácter y las de estilo.

El principio: el glosario es el oráculo del QA. Si el glosario está mal, todo
el reporte está mal. Por eso la validación corre SIEMPRE al cargar y reporta
ruidoso, en vez de tragarse los problemas como hacía load_translation_map().
"""

import csv
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from qa.checks.entities import ENTITY_PATTERN
from qa.normalize import normalize

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

ACCEPTED_SEPARATOR = "|"
PLACEHOLDER = re.compile(r"\{(\w+)\}")

# Valores basura que aparecen cuando alguien no terminó de llenar la hoja
SUSPICIOUS_VALUES = {"<<", ">>", "<", ">", "??", "?", "--", "-", "n/a", "na", "tbd", "xxx"}

# Caracteres que delatan que el glosario MISMO está corrupto
MOJIBAKE_IN_GLOSSARY = re.compile("[ÛÌÈÒ·]|â€|�")


class Policy(str, Enum):
    TRANSLATE = "translate"
    DO_NOT_TRANSLATE = "do_not_translate"
    PATTERN = "pattern"
    PENDING = "pending"


class Level(str, Enum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


VALID_RULE_TYPES = {"mojibake", "html_entity", "replacement_char", "lost_char", "unit", "typo"}
VALID_SEVERITIES = {"error", "warning", "info"}


@dataclass
class Issue:
    level: Level
    source: str
    row: int
    key: str
    message: str

    def __str__(self) -> str:
        return f"[{self.level.value.upper():7}] {self.source}:{self.row} ({self.key}) {self.message}"


@dataclass
class Entry:
    english: str
    spanish_canonical: str
    spanish_accepted: list[str] = field(default_factory=list)
    policy: Policy = Policy.TRANSLATE
    context: str = ""
    notes: str = ""
    row: int = 0

    @property
    def placeholders_en(self) -> set[str]:
        return set(PLACEHOLDER.findall(self.english))

    @property
    def placeholders_es(self) -> set[str]:
        return set(PLACEHOLDER.findall(self.spanish_canonical))

    def all_spanish(self) -> list[str]:
        values = [self.spanish_canonical] if self.spanish_canonical else []
        return values + self.spanish_accepted


@dataclass
class CharRule:
    pattern: str
    replacement: str
    rule_type: str
    severity: str
    auto_fixable: bool
    notes: str = ""
    row: int = 0


@dataclass
class StyleRule:
    rule_id: str
    description: str
    severity: str
    auto_fixable: bool
    notes: str = ""
    row: int = 0


class Glossary:
    """Glosario cargado, con índices en las dos direcciones."""

    def __init__(self, entries, char_rules, style_rules):
        self.entries = entries
        self.char_rules = char_rules
        self.style_rules = style_rules

        self.by_english: dict[str, Entry] = {}
        self.by_spanish: dict[str, tuple[Entry, str]] = {}
        self.patterns: list[Entry] = []

        for entry in entries:
            if entry.policy is Policy.PATTERN:
                self.patterns.append(entry)
                continue
            key = normalize(entry.english)
            if key and key not in self.by_english:
                self.by_english[key] = entry
            if entry.spanish_canonical:
                self.by_spanish.setdefault(normalize(entry.spanish_canonical), (entry, "canonical"))
            for variant in entry.spanish_accepted:
                self.by_spanish.setdefault(normalize(variant), (entry, "accepted"))

    def lookup_english(self, text: str):
        """Dado un texto en inglés, devuelve su entrada del glosario."""
        return self.by_english.get(normalize(text))

    def lookup_spanish(self, text: str):
        """Dado un texto en español, devuelve (entrada, 'canonical'|'accepted')."""
        return self.by_spanish.get(normalize(text))

    @property
    def pending(self):
        return [e for e in self.entries if e.policy is Policy.PENDING]

    def __len__(self) -> int:
        return len(self.entries)


def _read_csv(path: Path):
    # utf-8-sig: Excel escribe BOM y el equipo edita la hoja en Excel
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _flag(value) -> bool:
    return (value or "").strip().lower() in {"yes", "y", "true", "1", "si", "sí"}


def load_entries(path: Path):
    issues = []
    entries = []

    for index, raw in enumerate(_read_csv(path), start=2):
        english = (raw.get("english") or "").strip()
        canonical = (raw.get("spanish_canonical") or "").strip()
        accepted_raw = (raw.get("spanish_accepted") or "").strip()
        policy_raw = (raw.get("policy") or "").strip().lower()

        if not english:
            issues.append(Issue(Level.ERROR, "glossary", index, "-", "Row with no English term."))
            continue

        # Se revisa aqui, sobre el valor CRUDO: mas abajo ya viene stripped
        for label, original in (("english", raw.get("english") or ""),
                                ("spanish_canonical", raw.get("spanish_canonical") or "")):
            if original != original.strip() or "  " in original:
                issues.append(
                    Issue(Level.WARNING, "glossary", index, english,
                          f"{label} has stray whitespace: {original!r}")
                )

        try:
            policy = Policy(policy_raw)
        except ValueError:
            issues.append(
                Issue(Level.ERROR, "glossary", index, english,
                      f"invalid policy: {policy_raw!r}. Valid ones: {[p.value for p in Policy]}")
            )
            policy = Policy.TRANSLATE

        accepted = [v.strip() for v in accepted_raw.split(ACCEPTED_SEPARATOR) if v.strip()]

        entries.append(
            Entry(
                english=english,
                spanish_canonical=canonical,
                spanish_accepted=accepted,
                policy=policy,
                context=(raw.get("context") or "").strip(),
                notes=(raw.get("notes") or "").strip(),
                row=index,
            )
        )

    return entries, issues


def validate_entries(entries):
    issues = []
    seen_english = {}
    spanish_owners = {}

    for entry in entries:
        key = normalize(entry.english)
        row, name = entry.row, entry.english

        # 1. Claves duplicadas - antes se sobreescribían en silencio
        if key in seen_english:
            issues.append(
                Issue(Level.ERROR, "glossary", row, name,
                      f"Duplicate term (already on row {seen_english[key]}). "
                      "If they are valid variants, merge them into spanish_accepted.")
            )
        else:
            seen_english[key] = row

        # 2. Valores basura
        if entry.spanish_canonical.strip().lower() in SUSPICIOUS_VALUES:
            issues.append(
                Issue(Level.ERROR, "glossary", row, name,
                      f"spanish_canonical holds a junk value: {entry.spanish_canonical!r}")
            )

        # 3. El glosario mismo corrupto
        for label, value in (("spanish_canonical", entry.spanish_canonical), ("english", entry.english)):
            if MOJIBAKE_IN_GLOSSARY.search(value):
                issues.append(
                    Issue(Level.ERROR, "glossary", row, name, f"{label} contains mojibake: {value!r}")
                )
            if ENTITY_PATTERN.search(value):
                issues.append(
                    Issue(Level.ERROR, "glossary", row, name,
                          f"{label} contains an undecoded HTML entity: {value!r}")
                )

        # 4. Coherencia según la policy
        if entry.policy is Policy.TRANSLATE:
            if not entry.spanish_canonical:
                issues.append(
                    Issue(Level.ERROR, "glossary", row, name,
                          "policy=translate but there is no translation. Use policy=pending if you do not have it yet.")
                )
            elif normalize(entry.spanish_canonical) == key:
                issues.append(
                    Issue(Level.WARNING, "glossary", row, name,
                          "The translation is identical to the English. If intentional, mark do_not_translate.")
                )

        elif entry.policy is Policy.DO_NOT_TRANSLATE:
            if normalize(entry.spanish_canonical) != key:
                issues.append(
                    Issue(Level.WARNING, "glossary", row, name,
                          f"do_not_translate but the canonical differs from the English "
                          f"({entry.spanish_canonical!r}). Should it be translate?")
                )

        elif entry.policy is Policy.PATTERN:
            if not entry.placeholders_en:
                issues.append(
                    Issue(Level.ERROR, "glossary", row, name,
                          "policy=pattern but the English has no placeholders in braces.")
                )
            if entry.placeholders_en != entry.placeholders_es:
                issues.append(
                    Issue(Level.ERROR, "glossary", row, name,
                          f"Placeholders do not match: EN={sorted(entry.placeholders_en)} "
                          f"ES={sorted(entry.placeholders_es)}")
                )

        elif entry.policy is Policy.PENDING:
            issues.append(
                Issue(Level.WARNING, "glossary", row, name,
                      "PENDING term - QA cannot validate it until it has a translation.")
            )

        # 5. Variantes redundantes
        for variant in entry.spanish_accepted:
            if normalize(variant) == normalize(entry.spanish_canonical):
                issues.append(
                    Issue(Level.WARNING, "glossary", row, name,
                          f"Accepted variant {variant!r} equals the canonical one; it is redundant.")
                )

        if entry.spanish_canonical and entry.policy is not Policy.PATTERN:
            spanish_owners.setdefault(normalize(entry.spanish_canonical), []).append(entry.english)

    # 7. Misma traducción para varios términos - legítimo, pero hay que saberlo
    for spanish, owners in spanish_owners.items():
        if len(owners) > 1:
            issues.append(
                Issue(Level.INFO, "glossary", 0, ", ".join(owners),
                      f"They share the same Spanish translation ({spanish!r}). "
                      "That is valid, but QA cannot tell which one was expected.")
            )

    return issues


def load_char_rules(path: Path):
    issues = []
    rules = []
    seen = {}

    for index, raw in enumerate(_read_csv(path), start=2):
        pattern = raw.get("pattern") or ""
        if not pattern.strip():
            issues.append(Issue(Level.ERROR, "char_rules", index, "-", "Rule with no pattern."))
            continue

        rule = CharRule(
            pattern=pattern,
            replacement=raw.get("replacement") or "",
            rule_type=(raw.get("rule_type") or "").strip(),
            severity=(raw.get("severity") or "").strip(),
            auto_fixable=_flag(raw.get("auto_fixable")),
            notes=(raw.get("notes") or "").strip(),
            row=index,
        )

        if rule.rule_type not in VALID_RULE_TYPES:
            issues.append(
                Issue(Level.ERROR, "char_rules", index, pattern,
                      f"invalid rule_type: {rule.rule_type!r}. Valid ones: {sorted(VALID_RULE_TYPES)}")
            )
        if rule.severity not in VALID_SEVERITIES:
            issues.append(
                Issue(Level.ERROR, "char_rules", index, pattern,
                      f"invalid severity: {rule.severity!r}. Valid ones: {sorted(VALID_SEVERITIES)}")
            )
        if rule.auto_fixable and not rule.replacement:
            issues.append(
                Issue(Level.ERROR, "char_rules", index, pattern,
                      "auto_fixable=yes but there is no replacement. Set it to no, or fill replacement.")
            )
        if not rule.auto_fixable and rule.replacement:
            issues.append(
                Issue(Level.INFO, "char_rules", index, pattern,
                      f"auto_fixable=no but a replacement {rule.replacement!r} is set; "
                      "it will be used only as a suggestion.")
            )
        if pattern in seen:
            issues.append(
                Issue(Level.ERROR, "char_rules", index, pattern,
                      f"Duplicate pattern (already on row {seen[pattern]}).")
            )
        else:
            seen[pattern] = index

        rules.append(rule)

    # Patrones que se contienen entre sí: el orden de aplicación cambia el resultado
    for rule in rules:
        for other in rules:
            # La igualdad exacta ya la reporta el chequeo de duplicados
            if (
                rule is not other
                and rule.pattern
                and rule.pattern != other.pattern
                and rule.pattern in other.pattern
            ):
                issues.append(
                    Issue(Level.WARNING, "char_rules", rule.row, rule.pattern,
                          f"This pattern is contained in {other.pattern!r} (row {other.row}); "
                          "apply the longer one first.")
                )

    return rules, issues


def load_style_rules(path: Path):
    issues = []
    rules = []
    seen = {}

    for index, raw in enumerate(_read_csv(path), start=2):
        rule_id = (raw.get("rule_id") or "").strip()
        description = (raw.get("description") or "").strip()

        if not rule_id:
            issues.append(Issue(Level.ERROR, "style_rules", index, "-", "Rule with no rule_id."))
            continue
        if not description:
            issues.append(Issue(Level.ERROR, "style_rules", index, rule_id, "Rule with no description."))
        if rule_id in seen:
            issues.append(
                Issue(Level.ERROR, "style_rules", index, rule_id,
                      f"Duplicate rule_id (already on row {seen[rule_id]}).")
            )
        else:
            seen[rule_id] = index

        rules.append(
            StyleRule(
                rule_id=rule_id,
                description=description,
                severity=(raw.get("severity") or "").strip(),
                auto_fixable=_flag(raw.get("auto_fixable")),
                notes=(raw.get("notes") or "").strip(),
                row=index,
            )
        )

    return rules, issues


def load_glossary(data_dir=None):
    """Carga los tres archivos y devuelve el glosario junto con TODOS los problemas."""
    base = Path(data_dir) if data_dir else DATA_DIR

    entries, issues = load_entries(base / "glossary.csv")
    issues = issues + validate_entries(entries)

    char_rules, char_issues = load_char_rules(base / "char_rules.csv")
    issues = issues + char_issues

    style_rules, style_issues = load_style_rules(base / "style_rules.csv")
    issues = issues + style_issues

    return Glossary(entries, char_rules, style_rules), issues


def has_errors(issues) -> bool:
    return any(issue.level is Level.ERROR for issue in issues)


def summarize(issues):
    return {level.value: sum(1 for issue in issues if issue.level is level) for level in Level}
