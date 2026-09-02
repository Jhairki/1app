"""CLI: validate the glossary and rules before running any scan.

    python validate_glossary.py

Exits with code 1 when there are errors, so it can gate a CI pipeline.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from qa.glossary import Level, has_errors, load_glossary, summarize

ICONS = {Level.ERROR: "X", Level.WARNING: "!", Level.INFO: "i"}


def main() -> int:
    glossary, issues = load_glossary()

    print("=" * 78)
    print("GLOSSARY VALIDATION")
    print("=" * 78)
    print(
        f"  {len(glossary)} terms"
        f" | {len(glossary.char_rules)} character rules"
        f" | {len(glossary.style_rules)} style rules"
    )
    print(
        f"  indexes: {len(glossary.by_english)} EN->ES"
        f" | {len(glossary.by_spanish)} ES->EN"
        f" | {len(glossary.patterns)} patterns"
        f" | {len(glossary.pending)} pending"
    )

    counts = summarize(issues)
    print(
        f"  issues: {counts['error']} errors"
        f" | {counts['warning']} warnings"
        f" | {counts['info']} informational"
    )
    print()

    for level in (Level.ERROR, Level.WARNING, Level.INFO):
        selected = [i for i in issues if i.level is level]
        if not selected:
            continue
        print(f"--- {level.value.upper()} ({len(selected)}) " + "-" * (60 - len(level.value)))
        for issue in selected:
            location = f"{issue.source}:{issue.row}" if issue.row else issue.source
            print(f"  {ICONS[level]} {location:<16} {issue.key}")
            print(f"      {issue.message}")
        print()

    if has_errors(issues):
        print("RESULT: the glossary has errors. Fix them before scanning.")
        return 1

    print("RESULT: glossary is usable.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
