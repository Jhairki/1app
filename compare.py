"""CLI: Stare and Compare — el sitio migrado contra el original.

    python compare.py --source oldsite.com --copy new.cms.dealer.com --paths / /service/

A diferencia de scan.py, aca los dos textos deben ser IGUALES: no se traduce
nada, se copia. Cualquier diferencia es sospechosa.

Exits with code 1 when there are errors, so it can gate a CI pipeline.
"""

import argparse
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from qa.bugreport import group_repeated
from qa.report_html import write as write_html
from qa.screenshots import collect as collect_shots
from qa.export import by_path, write_csv
from qa.glossary import load_glossary
from qa.browser import check_popups_live
from qa.migration import compare_sites

MARKS = {"error": "X", "warning": "!", "info": "i"}
ORDER = {"error": 0, "warning": 1, "info": 2}


def read_paths(args) -> list[str]:
    """Los paths vienen por argumento o desde un archivo, uno por linea."""
    paths = list(args.paths or [])
    if args.paths_file:
        contenido = Path(args.paths_file).read_text(encoding="utf-8-sig")
        paths += [line.strip() for line in contenido.splitlines()
                  if line.strip() and not line.strip().startswith("#")]
    # Sin duplicados, conservando el orden en que se dieron
    vistos, unicos = set(), []
    for p in paths:
        if p not in vistos:
            vistos.add(p)
            unicos.append(p)
    return unicos


def print_report(result) -> None:
    summary = result.summary()

    print()
    print("=" * 88)
    print("STARE AND COMPARE")
    print(f"  source : {result.source_site}")
    print(f"  copy   : {result.copy_site}")
    print("=" * 88)
    print(
        f"  {summary['pages_scanned']} pages compared"
        f" | {summary['units_checked']} texts checked"
        f" | {summary['pages_failed']} pages failed"
    )
    print(
        f"  {summary['errors']} errors"
        f" | {summary['warnings']} warnings"
        f" | {summary['infos']} informational"
    )

    if summary["by_verdict"]:
        print()
        print("  By finding type:")
        for verdict, count in summary["by_verdict"].items():
            print(f"    {count:>4}  {verdict}")

    resumen = [r for r in by_path(result) if r["errores"] or r["advertencias"] or r["error"]]
    if len(result.pages) > 1 and resumen:
        print()
        print("  Pages with findings:")
        ancho = max(len(r["path"]) for r in resumen)
        for r in resumen:
            if r["error"]:
                print(f"    {r['path']:<{ancho}}  FAILED")
                continue
            tipos = " ".join(f"{k}={v}" for k, v in r["tipos"].items())
            print(f"    {r['path']:<{ancho}}  {r['errores']}E {r['advertencias']}A   {tipos}")

    for page in result.pages:
        if page.error:
            print()
            print(f"--- {page.path}")
            print(f"    FAILED: {page.error}")
            continue
        if not page.findings:
            continue

        print()
        print("-" * 88)
        print(f"{page.path}   ({page.errors} errors of {len(page.findings)} findings)")
        print(f"  source : {page.source_url}")
        print(f"  copy   : {page.copy_url}")

        for finding in sorted(page.findings, key=lambda f: ORDER[f.severity.value]):
            print()
            print(f"  {MARKS[finding.severity.value]} [{finding.verdict.value}]")
            if finding.found:
                print(f"      on the copy   : {finding.found[:110]!r}")
            if finding.expected:
                print(f"      on the source : {finding.expected[:110]!r}")
            print(f"      {finding.message}")
            if finding.context:
                print(f"      context       : {finding.context[:100]}")

    print()
    print("=" * 88)
    if summary["errors"]:
        print(f"RESULT: {summary['errors']} errors. The migration is not faithful yet.")
    else:
        print("RESULT: no errors. The copy matches the source.")



def print_bugs(result, device: str) -> None:
    """Los hallazgos en el formato de bugs del equipo, listos para pegar."""
    grupos = group_repeated(result, device)
    if not grupos:
        return

    print()
    print("=" * 88)
    print("BUG REPORT FORMAT  —  Field 1 | Field 2 | Field 3 | Field 4")
    print("=" * 88)
    for g in grupos:
        print()
        print(f"  {g['bug']}")
        if len(g["paths"]) > 1:
            print(f"      on {len(g['paths'])} pages: {', '.join(g['paths'][:6])}"
                  + (" ..." if len(g["paths"]) > 6 else ""))
            print("      Same bug on several pages — check with whoever worked on the request.")
        else:
            print(f"      {g['paths'][0]}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Stare and Compare: check a migrated site against its source."
    )
    parser.add_argument("--source", required=True,
                        help="Domain of the original site, the one being copied from")
    parser.add_argument("--copy", required=True, dest="copy_site",
                        help="Domain of the migrated site, usually the CMS one")
    parser.add_argument("--paths", nargs="*", help="Paths to compare, the same on both sites")
    parser.add_argument("--paths-file", help="File with one path per line")
    parser.add_argument("--csv", dest="csv_path", help="Save the report as CSV (Excel)")
    parser.add_argument("--json", dest="json_path", help="Save the report as JSON")
    parser.add_argument("--popups", action="store_true",
                        help="Use a real browser to check popups open on both sites (slow)")
    parser.add_argument("--shots", action="store_true",
                        help="Attach a cropped screenshot of each bug to the HTML report (slow)")
    parser.add_argument("--html", dest="html_path",
                        help="Save the report in the team Test & Feedback format")
    parser.add_argument("--bugs", action="store_true",
                        help="Print the findings in the team bug-report format")
    parser.add_argument("--mobile", action="store_true",
                        help="Request the pages as a phone would, and report Field 1 as M")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )

    paths = read_paths(args)
    if not paths:
        print("No paths given. Use --paths / /service/  or  --paths-file paths.txt")
        return 1

    # El glosario no se valida aca: en una migracion no se traduce. Solo se
    # aprovechan sus reglas de caracteres para detectar mojibake introducido.
    glossary, _ = load_glossary()

    result = compare_sites(args.source, args.copy_site, paths,
                           char_rules=glossary.char_rules, mobile=args.mobile)
    if result.error:
        print(f"Comparison failed: {result.error}")
        return 1

    if args.popups:
        print()
        print("Checking popups with a real browser (this takes a while)...")
        for page in result.pages:
            if page.error:
                continue
            # El original hace de referencia, igual que la pagina inglesa en scan.py
            hallazgos = check_popups_live(page.copy_url, page.source_url, page.path)
            if hallazgos:
                page.findings.extend(hallazgos)
                print(f"  {page.path}: {len(hallazgos)} behavior findings")

    print_report(result)

    device = "M" if args.mobile else "D"
    if args.bugs:
        print_bugs(result, device)

    shots = None
    if args.html_path and args.shots:
        print()
        print("Capturing screenshots (this takes a while)...")
        shots = collect_shots(result, device)
        print(f"  {sum(len(v) for v in shots.values())} screenshots captured")

    if args.html_path:
        bugs = write_html(result, args.html_path, device,
                          "Stare and Compare Report", shots=shots)
        print()
        print(f"HTML report saved to {args.html_path} ({bugs} bugs)")

    if args.csv_path:
        filas = write_csv(result, args.csv_path, device)
        print()
        print(f"CSV saved to {args.csv_path} ({filas} rows)")

    if args.json_path:
        payload = {
            "source_site": result.source_site,
            "copy_site": result.copy_site,
            "summary": result.summary(),
            "pages": [
                {
                    "path": page.path,
                    "source_url": page.source_url,
                    "copy_url": page.copy_url,
                    "error": page.error,
                    "units_checked": page.units_checked,
                    "findings": [f.as_dict() for f in page.findings],
                }
                for page in result.pages
            ],
        }
        Path(args.json_path).write_text(
            json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        print(f"JSON saved to {args.json_path}")

    return 1 if result.summary()["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
