"""Exportar el reporte a CSV.

El equipo trabaja el glosario en Excel, asi que el reporte sale en el mismo
formato: una fila por hallazgo, con el path y la URL de cada lado para poder
abrir la pagina y verificarlo.
"""

import csv
import io

COLUMNS = [
    "path",
    "severity",
    "type",
    "found",
    "expected",
    "auto_fixable",
    "fix",
    "message",
    "context",
    "url_es",
    "url_en",
]

SEVERITY_ORDER = {"error": 0, "warning": 1, "info": 2}


def rows(result):
    """Una fila por hallazgo, los errores primero."""
    for page in sorted(result.pages, key=lambda p: p.path):
        for finding in sorted(page.findings,
                              key=lambda f: SEVERITY_ORDER[f.severity.value]):
            yield {
                "path": page.path,
                "severity": finding.severity.value,
                "type": finding.verdict.value,
                "found": finding.found,
                "expected": finding.expected,
                "auto_fixable": "yes" if finding.auto_fixable else "no",
                "fix": finding.fixed,
                "message": finding.message,
                "context": finding.context,
                "url_es": page.spanish_url,
                "url_en": page.english_url,
            }


def to_csv(result) -> str:
    """El reporte completo como texto CSV."""
    salida = io.StringIO()
    writer = csv.DictWriter(salida, fieldnames=COLUMNS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows(result))
    return salida.getvalue()


def write_csv(result, path) -> int:
    """Guarda el CSV y devuelve cuantas filas escribio.

    utf-8-sig: sin el BOM, Excel en Windows abre los acentos como mojibake --
    justo el bug que esta herramienta busca.
    """
    contenido = to_csv(result)
    with open(path, "w", encoding="utf-8-sig", newline="") as handle:
        handle.write(contenido)
    return contenido.count("\n") - 1


def by_path(result) -> list[dict]:
    """Resumen por pagina: cuantos hallazgos de cada tipo tiene cada path."""
    resumen = []
    for page in result.pages:
        if page.error:
            resumen.append({"path": page.path, "error": page.error,
                            "errores": 0, "advertencias": 0, "tipos": {}})
            continue
        tipos: dict[str, int] = {}
        for finding in page.findings:
            tipos[finding.verdict.value] = tipos.get(finding.verdict.value, 0) + 1
        resumen.append({
            "path": page.path,
            "error": "",
            "errores": page.errors,
            "advertencias": sum(1 for f in page.findings
                                if f.severity.value == "warning"),
            "tipos": dict(sorted(tipos.items(), key=lambda kv: -kv[1])),
        })
    return resumen
