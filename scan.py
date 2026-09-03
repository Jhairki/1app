"""CLI: scan a site and report the QA findings.

    python scan.py https://mydealer.com
    python scan.py https://mydealer.com --max-pages 5
    python scan.py https://mydealer.com --paths /inventory/ /service/
    python scan.py https://mydealer.com --csv report.csv

Exits with code 1 when there are errors, so it can gate a CI pipeline.
"""

import argparse
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from qa.browser import check_popups_live
from qa.bugreport import group_repeated
from qa.report_html import write as write_html
from qa.engine import scan_site
from qa.export import by_path, write_csv
from qa.findings import Severity
from qa.glossary import Level, has_errors, load_glossary

MARKS = {"error": "X", "warning": "!", "info": "i"}
ORDER = {"error": 0, "warning": 1, "info": 2}


def print_report(result) -> None:
    summary = result.summary()

    print()
    print("=" * 88)
    print(f"LOCALIZATION QA  -  {result.base_url}")
    print("=" * 88)
    print(
        f"  {summary['pages_scanned']} pages scanned"
        f" | {summary['units_checked']} texts checked"
        f" | {summary['pages_failed']} pages failed"
    )
    print(
        f"  {summary['errors']} errors"
        f" | {summary['warnings']} warnings"
        f" | {summary['infos']} informational"
        f" | {summary['auto_fixable']} auto-fixable"
    )
    print(f"  pages with errors: {summary['affected_pages']}")

    if summary["by_verdict"]:
        print()
        print("  By finding type:")
        for verdict, count in summary["by_verdict"].items():
            print(f"    {count:>4}  {verdict}")

    resumen_paths = [r for r in by_path(result) if r["errores"] or r["advertencias"] or r["error"]]
    if len(result.pages) > 1 and resumen_paths:
        print()
        print("  Pages with findings:")
        ancho = max(len(r["path"]) for r in resumen_paths)
        for r in resumen_paths:
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
        print(f"  ES: {page.spanish_url}")
        print(f"  EN: {page.english_url}")

        for finding in sorted(page.findings, key=lambda f: ORDER[f.severity.value]):
            print()
            print(f"  {MARKS[finding.severity.value]} [{finding.verdict.value}]")
            if finding.found:
                print(f"      found    : {finding.found!r}")
            if finding.expected:
                print(f"      expected : {finding.expected!r}")
            print(f"      {finding.message}")
            if finding.auto_fixable:
                print(f"      fix to   : {finding.fixed!r}")
            if finding.context:
                print(f"      context  : {finding.context[:100]}")

    print()
    print("=" * 88)
    if summary["errors"]:
        print(f"RESULT: {summary['errors']} errors. Not ready to publish.")
    else:
        print("RESULT: no errors.")



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
    parser = argparse.ArgumentParser(description="EN->ES localization QA for dealer sites.")
    parser.add_argument("base_url", help="Base URL of the site")
    parser.add_argument("--paths", nargs="*", help="Paths to check. Taken from the navigation by default.")
    parser.add_argument("--max-pages", type=int, default=0, help="Maximum number of pages to scan")
    parser.add_argument("--json", dest="json_path", help="Save the report as JSON")
    parser.add_argument("--popups", action="store_true",
                        help="Use a real browser to verify popups open (slow)")
    parser.add_argument("--csv", dest="csv_path", help="Save the report as CSV (Excel)")
    parser.add_argument("--unknown", action="store_true",
                        help="Include terms missing from the glossary (very noisy)")
    parser.add_argument("--skip-glossary-check", action="store_true",
                        help="Scan even if the glossary has errors")
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

    glossary, issues = load_glossary()
    if has_errors(issues) and not args.skip_glossary_check:
        print("The glossary has errors; fix them before scanning:")
        for issue in issues:
            if issue.level is Level.ERROR:
                print(f"  X {issue.source}:{issue.row} ({issue.key}) {issue.message}")
        print()
        print("Run  python validate_glossary.py  for the full detail.")
        return 1

    result = scan_site(
        args.base_url,
        paths=args.paths or None,
        glossary=glossary,
        glossary_issues=issues,
        max_pages=args.max_pages,
        report_unknown=args.unknown,
        mobile=args.mobile,
    )

    if result.error:
        print(f"Scan failed: {result.error}")
        return 1

    if args.popups:
        print()
        print("Verifying popups with a real browser (this takes a while)...")
        for page in result.pages:
            if page.error:
                continue
            hallazgos = check_popups_live(page.spanish_url, page.english_url, page.path)
            if hallazgos:
                page.findings.extend(hallazgos)
                print(f"  {page.path}: {len(hallazgos)} behavior findings")

    print_report(result)

    device = "M" if args.mobile else "D"
    if args.bugs:
        print_bugs(result, device)

    if args.html_path:
        bugs = write_html(result, args.html_path, device, "Localization QA Report")
        print()
        print(f"HTML report saved to {args.html_path} ({bugs} bugs)")

    if args.csv_path:
        filas = write_csv(result, args.csv_path, device)
        print()
        print(f"CSV saved to {args.csv_path} ({filas} rows)")

    if args.json_path:
        payload = {
            "base_url": result.base_url,
            "summary": result.summary(),
            "pages": [
                {
                    "path": page.path,
                    "spanish_url": page.spanish_url,
                    "english_url": page.english_url,
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
        print(f"\nJSON saved to {args.json_path}")

    return 1 if result.summary()["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
