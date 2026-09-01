"""CLI: escanea un sitio y reporta los hallazgos de QA en español.

    python scan.py https://midealer.com
    python scan.py https://midealer.com --max-pages 5
    python scan.py https://midealer.com --paths /inventario/ /servicio/
    python scan.py https://midealer.com --json reporte.json

Sale con codigo 1 si hay errores, para encadenarlo en CI.
"""

import argparse
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

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
    print(f"QA DE LOCALIZACION  -  {result.base_url}")
    print("=" * 88)
    print(
        f"  {summary['pages_scanned']} paginas escaneadas"
        f" | {summary['units_checked']} textos revisados"
        f" | {summary['pages_failed']} paginas fallidas"
    )
    print(
        f"  {summary['errors']} errores"
        f" | {summary['warnings']} advertencias"
        f" | {summary['infos']} informativos"
        f" | {summary['auto_fixable']} auto-corregibles"
    )
    print(f"  paginas con errores: {summary['affected_pages']}")

    if summary["by_verdict"]:
        print()
        print("  Por tipo de hallazgo:")
        for verdict, count in summary["by_verdict"].items():
            print(f"    {count:>4}  {verdict}")

    resumen_paths = [r for r in by_path(result) if r["errores"] or r["advertencias"] or r["error"]]
    if len(result.pages) > 1 and resumen_paths:
        print()
        print("  Paginas con hallazgos:")
        ancho = max(len(r["path"]) for r in resumen_paths)
        for r in resumen_paths:
            if r["error"]:
                print(f"    {r['path']:<{ancho}}  FALLO")
                continue
            tipos = " ".join(f"{k}={v}" for k, v in r["tipos"].items())
            print(f"    {r['path']:<{ancho}}  {r['errores']}E {r['advertencias']}A   {tipos}")

    for page in result.pages:
        if page.error:
            print()
            print(f"--- {page.path}")
            print(f"    FALLO: {page.error}")
            continue
        if not page.findings:
            continue

        print()
        print("-" * 88)
        print(f"{page.path}   ({page.errors} errores de {len(page.findings)} hallazgos)")
        print(f"  ES: {page.spanish_url}")
        print(f"  EN: {page.english_url}")

        for finding in sorted(page.findings, key=lambda f: ORDER[f.severity.value]):
            print()
            print(f"  {MARKS[finding.severity.value]} [{finding.verdict.value}]")
            if finding.found:
                print(f"      encontrado : {finding.found!r}")
            if finding.expected:
                print(f"      esperado   : {finding.expected!r}")
            print(f"      {finding.message}")
            if finding.auto_fixable:
                print(f"      corregir a : {finding.fixed!r}")
            if finding.context:
                print(f"      contexto   : {finding.context[:100]}")

    print()
    print("=" * 88)
    if summary["errors"]:
        print(f"RESULTADO: {summary['errors']} errores. La pagina no esta lista.")
    else:
        print("RESULTADO: sin errores.")


def main() -> int:
    parser = argparse.ArgumentParser(description="QA de localizacion EN->ES para sitios de dealers.")
    parser.add_argument("base_url", help="URL base del sitio")
    parser.add_argument("--paths", nargs="*", help="Paths a revisar. Por defecto salen de la navegacion.")
    parser.add_argument("--max-pages", type=int, default=0, help="Limite de paginas a escanear")
    parser.add_argument("--json", dest="json_path", help="Guardar el reporte como JSON")
    parser.add_argument("--csv", dest="csv_path", help="Guardar el reporte como CSV (Excel)")
    parser.add_argument("--unknown", action="store_true",
                        help="Incluir los terminos que no estan en el glosario (mucho ruido)")
    parser.add_argument("--skip-glossary-check", action="store_true",
                        help="Escanear aunque el glosario tenga errores")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )

    glossary, issues = load_glossary()
    if has_errors(issues) and not args.skip_glossary_check:
        print("El glosario tiene errores; corrigelos antes de escanear:")
        for issue in issues:
            if issue.level is Level.ERROR:
                print(f"  X {issue.source}:{issue.row} ({issue.key}) {issue.message}")
        print()
        print("Corre  python validate_glossary.py  para el detalle completo.")
        return 1

    result = scan_site(
        args.base_url,
        paths=args.paths or None,
        glossary=glossary,
        glossary_issues=issues,
        max_pages=args.max_pages,
        report_unknown=args.unknown,
    )

    if result.error:
        print(f"El escaneo fallo: {result.error}")
        return 1

    print_report(result)

    if args.csv_path:
        filas = write_csv(result, args.csv_path)
        print()
        print(f"CSV guardado en {args.csv_path} ({filas} filas)")

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
        print(f"\nJSON guardado en {args.json_path}")

    return 1 if result.summary()["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
