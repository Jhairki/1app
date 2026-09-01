"""CLI: valida el glosario y las reglas antes de correr cualquier escaneo.

    python validate_glossary.py

Sale con codigo 1 si hay errores, para poder encadenarlo en CI.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from qa.glossary import Level, has_errors, load_glossary, summarize

ICONS = {Level.ERROR: "X", Level.WARNING: "!", Level.INFO: "i"}


def main() -> int:
    glossary, issues = load_glossary()

    print("=" * 78)
    print("VALIDACION DEL GLOSARIO")
    print("=" * 78)
    print(
        f"  {len(glossary)} terminos"
        f" | {len(glossary.char_rules)} reglas de caracter"
        f" | {len(glossary.style_rules)} reglas de estilo"
    )
    print(
        f"  indices: {len(glossary.by_english)} EN->ES"
        f" | {len(glossary.by_spanish)} ES->EN"
        f" | {len(glossary.patterns)} patrones"
        f" | {len(glossary.pending)} pendientes"
    )

    counts = summarize(issues)
    print(
        f"  hallazgos: {counts['error']} errores"
        f" | {counts['warning']} advertencias"
        f" | {counts['info']} informativos"
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
        print("RESULTADO: el glosario tiene errores. Corrigelos antes de escanear.")
        return 1

    print("RESULTADO: glosario utilizable.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
