"""Interfaz web del QA de localizacion.

El escaneo corre en un hilo aparte y la pagina consulta el avance, porque un
sitio de 10 paginas son ~30 segundos de descargas y una peticion sincrona
pareceria colgada.
"""

import logging
import os
import threading
import uuid
from pathlib import Path

from dotenv import load_dotenv
from flask import (Flask, Response, jsonify, redirect, render_template,
                   request, url_for)

load_dotenv(Path(__file__).resolve().parent / ".env")

from qa.engine import scan_site
from qa.export import by_path, to_csv
from qa.glossary import Level, load_glossary, summarize

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-key")

# Trabajos en memoria. Alcanza para una herramienta interna de un equipo;
# si algun dia corre para varios usuarios a la vez, esto va a Redis.
JOBS: dict[str, dict] = {}
JOBS_LOCK = threading.Lock()

SEVERITY_ORDER = {"error": 0, "warning": 1, "info": 2}

VERDICT_LABELS = {
    "broken_key": "Clave interna del CMS",
    "broken_key_source": "Clave rota tambien en ingles",
    "html_entity": "Entidad HTML visible",
    "mojibake": "Caracter corrupto",
    "lost_char": "Caracter perdido",
    "untranslated": "Sin traducir",
    "off_glossary": "Fuera de glosario",
    "near_miss": "Casi correcto",
    "case_mismatch": "Mayusculas distintas al ingles",
    "accepted_variant": "Variante aceptada",
    "unknown_term": "Termino nuevo",
    "proper_noun_altered": "Nombre propio alterado",
    "duplicate_term": "Termino duplicado en la pagina",
    "missing": "Contenido faltante",
    "locale_not_applied": "El sitio ignoro el locale",
    "unit_not_converted": "Unidad sin convertir",
    "unit_mislabeled": "Unidad mal etiquetada",
    "unit_unverifiable": "Unidad no verificable",
    "style_violation": "Regla de estilo",
}


def _update(job_id: str, **fields) -> None:
    with JOBS_LOCK:
        if job_id in JOBS:
            JOBS[job_id].update(fields)


def _run_scan(job_id: str, base_url: str, paths, max_pages: int) -> None:
    def on_progress(done: int, total: int, current: str) -> None:
        _update(job_id, done=done, total=total, current=current)

    try:
        glossary, issues = load_glossary()
        _update(job_id, glossary_issues=issues)

        result = scan_site(
            base_url,
            paths=paths,
            glossary=glossary,
            glossary_issues=issues,
            max_pages=max_pages,
            on_progress=on_progress,
        )
        if result.error:
            _update(job_id, state="failed", error=result.error)
        else:
            _update(job_id, state="done", result=result)
    except Exception as exc:
        logger.exception("El escaneo fallo para %s", base_url)
        _update(job_id, state="failed", error=str(exc))


@app.route("/", methods=["GET", "POST"])
def index():
    glossary, issues = load_glossary()
    counts = summarize(issues)

    if request.method == "POST":
        base_url = (request.form.get("base_url") or "").strip()
        if not base_url:
            return render_template(
                "index.html",
                error="Escribe la URL del sitio.",
                glossary=glossary,
                glossary_counts=counts,
            )

        raw_paths = (request.form.get("paths") or "").strip()
        paths = [p.strip() for p in raw_paths.splitlines() if p.strip()] or None

        try:
            max_pages = int(request.form.get("max_pages") or 0)
        except ValueError:
            max_pages = 0

        job_id = uuid.uuid4().hex[:12]
        with JOBS_LOCK:
            JOBS[job_id] = {
                "state": "running",
                "base_url": base_url,
                "done": 0,
                "total": max_pages or 0,
                "current": "",
                "result": None,
                "error": "",
                "glossary_issues": [],
            }

        threading.Thread(
            target=_run_scan,
            args=(job_id, base_url, paths, max_pages),
            daemon=True,
        ).start()

        return redirect(url_for("job", job_id=job_id))

    return render_template("index.html", glossary=glossary, glossary_counts=counts)


@app.route("/scan/<job_id>")
def job(job_id: str):
    with JOBS_LOCK:
        data = JOBS.get(job_id)

    if data is None:
        return redirect(url_for("index"))

    if data["state"] == "running":
        return render_template("progress.html", job_id=job_id, job=data)

    if data["state"] == "failed":
        return render_template("report.html", job=data, result=None, error=data["error"])

    result = data["result"]
    findings = sorted(
        result.findings,
        key=lambda f: (SEVERITY_ORDER[f.severity.value], f.path, f.verdict.value),
    )
    return render_template(
        "report.html",
        job=data,
        result=result,
        summary=result.summary(),
        findings=findings,
        labels=VERDICT_LABELS,
        glossary_errors=[i for i in data["glossary_issues"] if i.level is Level.ERROR],
        por_path=[r for r in by_path(result) if r["errores"] or r["advertencias"] or r["error"]],
        job_id=job_id,
        error=None,
    )


@app.route("/scan/<job_id>/csv")
def job_csv(job_id: str):
    """Descarga el reporte como CSV para abrirlo en Excel."""
    with JOBS_LOCK:
        data = JOBS.get(job_id)

    if data is None or data["state"] != "done":
        return redirect(url_for("index"))

    # utf-8-sig: sin BOM, Excel en Windows rompe los acentos
    contenido = to_csv(data["result"]).encode("utf-8-sig")
    nombre = f"qa-{job_id}.csv"
    return Response(
        contenido,
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{nombre}"'},
    )


@app.route("/scan/<job_id>/status")
def job_status(job_id: str):
    with JOBS_LOCK:
        data = JOBS.get(job_id)
    if data is None:
        return jsonify({"state": "missing"}), 404
    return jsonify({
        "state": data["state"],
        "done": data["done"],
        "total": data["total"],
        "current": data["current"],
        "error": data["error"],
    })


@app.route("/glosario")
def glossary_view():
    glossary, issues = load_glossary()
    return render_template(
        "glossary.html",
        glossary=glossary,
        issues=sorted(issues, key=lambda i: SEVERITY_ORDER.get(i.level.value, 3)),
        counts=summarize(issues),
    )


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
