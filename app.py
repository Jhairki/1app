"""Interfaz web de las dos herramientas de QA.

Son dos procesos distintos y viven en secciones separadas:

  /localization   ingles -> español, contra el glosario. Los dos textos DEBEN
                  diferir y lo que se valida es que la traduccion sea la oficial.

  /compare        Stare and Compare: sitio original -> sitio migrado. Los dos
                  textos deben ser IGUALES y cualquier diferencia es sospechosa.

Comparten el reporte, el CSV y el formato de bugs del equipo, pero no la logica.

El escaneo corre en un hilo aparte y la pagina consulta el avance, porque un
sitio de 10 paginas son ~30 segundos de descargas y una peticion sincrona
pareceria colgada.
"""

import logging
import os
import threading
import uuid
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from flask import (Flask, Response, jsonify, redirect, render_template,
                   request, url_for)

load_dotenv(Path(__file__).resolve().parent / ".env")

from qa.bugreport import group_repeated
from qa.engine import scan_site
from qa.export import by_path, to_csv
from qa.glossary import Level, load_glossary, summarize
from qa.migration import compare_sites
from qa.report_html import build as build_html
from qa.screenshots import collect as collect_shots

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

TITULOS = {
    "localization": "Localization QA Report",
    "compare": "Stare and Compare Report",
}

VERDICT_LABELS = {
    "broken_key": "CMS key",
    "broken_key_source": "CMS key broken in English too",
    "html_entity": "HTML entity",
    "mojibake": "Corrupt character",
    "lost_char": "Lost character",
    "untranslated": "Untranslated",
    "off_glossary": "Off glossary",
    "near_miss": "Near miss",
    "case_mismatch": "Capitalization",
    "accepted_variant": "Accepted variant",
    "unknown_term": "New term",
    "proper_noun_altered": "Proper noun altered",
    "duplicate_term": "Duplicate on page",
    "missing": "Missing content",
    "locale_not_applied": "Locale ignored",
    "popup_missing": "Popup not migrated",
    "popup_extra": "Popup only on one site",
    "popup_broken": "Popup does not open",
    "popup_broken_source": "Popup broken on both sites",
    "popup_unverified": "Popup unverified",
    "unit_not_converted": "Unit not converted",
    "unit_mislabeled": "Unit mislabeled",
    "unit_unverifiable": "Unit unverifiable",
    "style_violation": "Style rule",
    # Stare and Compare
    "text_changed": "Text changed",
    "content_missing": "Content missing",
    "content_extra": "Content not on source",
    "source_leak": "Still points at the source site",
    "count_mismatch": "Element count differs",
}


def _update(job_id: str, **fields) -> None:
    with JOBS_LOCK:
        if job_id in JOBS:
            JOBS[job_id].update(fields)


def _nuevo_job(kind: str, titulo: str, total: int, mobile: bool) -> str:
    job_id = uuid.uuid4().hex[:12]
    with JOBS_LOCK:
        JOBS[job_id] = {
            "kind": kind,
            "state": "running",
            "title": titulo,
            "started": datetime.now(),
            "device": "M" if mobile else "D",
            "done": 0,
            "total": total,
            "current": "",
            "result": None,
            "error": "",
            "glossary_issues": [],
            "shots": None,
            "want_shots": False,
        }
    return job_id


def _run(job_id: str, funcion) -> None:
    """Corre el escaneo en segundo plano y guarda el resultado o el error."""
    def on_progress(done: int, total: int, current: str) -> None:
        _update(job_id, done=done, total=total, current=current)

    try:
        result = funcion(on_progress)
        if result.error:
            _update(job_id, state="failed", error=result.error)
            return

        with JOBS_LOCK:
            quiere = JOBS.get(job_id, {}).get("want_shots")
            device = JOBS.get(job_id, {}).get("device", "D")

        shots = None
        if quiere:
            _update(job_id, current="capturing screenshots...")
            try:
                shots = collect_shots(result, device)
            except Exception as exc:
                # Sin capturas el reporte sale igual; no vale colgar el trabajo
                logger.warning("Screenshots failed: %s", exc)

        _update(job_id, state="done", result=result, shots=shots)
    except Exception as exc:
        logger.exception("Job %s failed", job_id)
        _update(job_id, state="failed", error=str(exc))


# --------------------------------------------------------------------------
# Portada
# --------------------------------------------------------------------------

@app.route("/")
def home():
    glossary, issues = load_glossary()
    return render_template("home.html", glossary=glossary,
                           glossary_counts=summarize(issues), active="home")


# --------------------------------------------------------------------------
# QA de localizacion: ingles -> español
# --------------------------------------------------------------------------

@app.route("/localization", methods=["GET", "POST"])
def localization():
    glossary, issues = load_glossary()
    counts = summarize(issues)

    if request.method == "POST":
        base_url = (request.form.get("base_url") or "").strip()
        if not base_url:
            return render_template("localization.html", error="Enter the site URL.",
                                   glossary=glossary, glossary_counts=counts,
                                   active="localization")

        raw = (request.form.get("paths") or "").strip()
        paths = [p.strip() for p in raw.splitlines() if p.strip()] or None
        try:
            max_pages = int(request.form.get("max_pages") or 0)
        except ValueError:
            max_pages = 0
        mobile = bool(request.form.get("mobile"))

        job_id = _nuevo_job("localization", base_url, max_pages or 0, mobile)
        _update(job_id, glossary_issues=issues,
                want_shots=bool(request.form.get("shots")))

        threading.Thread(
            target=_run,
            args=(job_id, lambda cb: scan_site(
                base_url, paths=paths, glossary=glossary, glossary_issues=issues,
                max_pages=max_pages, on_progress=cb, mobile=mobile)),
            daemon=True,
        ).start()
        return redirect(url_for("job", job_id=job_id))

    return render_template("localization.html", glossary=glossary,
                           glossary_counts=counts, active="localization")


# --------------------------------------------------------------------------
# Stare and Compare: original -> migrado
# --------------------------------------------------------------------------

@app.route("/compare", methods=["GET", "POST"])
def compare():
    if request.method == "POST":
        source = (request.form.get("source") or "").strip()
        copy_site = (request.form.get("copy_site") or "").strip()
        raw = (request.form.get("paths") or "").strip()
        paths = [p.strip() for p in raw.splitlines() if p.strip()]

        falta = None
        if not source or not copy_site:
            falta = "Enter both the source site and the migrated site."
        elif not paths:
            falta = "Enter at least one path to compare."
        if falta:
            return render_template("compare.html", error=falta, active="compare")

        mobile = bool(request.form.get("mobile"))
        glossary, _ = load_glossary()

        verify_links = bool(request.form.get("links"))

        job_id = _nuevo_job("compare", f"{source} → {copy_site}", len(paths), mobile)
        _update(job_id, want_shots=bool(request.form.get("shots")))
        threading.Thread(
            target=_run,
            args=(job_id, lambda cb: compare_sites(
                source, copy_site, paths, char_rules=glossary.char_rules,
                on_progress=cb, mobile=mobile, verify_links=verify_links)),
            daemon=True,
        ).start()
        return redirect(url_for("job", job_id=job_id))

    return render_template("compare.html", active="compare")


# --------------------------------------------------------------------------
# Reporte, comun a los dos
# --------------------------------------------------------------------------

@app.route("/scan/<job_id>")
def job(job_id: str):
    with JOBS_LOCK:
        data = JOBS.get(job_id)

    if data is None:
        return redirect(url_for("home"))

    activo = data["kind"]

    if data["state"] == "running":
        return render_template("progress.html", job_id=job_id, job=data, active=activo)

    if data["state"] == "failed":
        return render_template("report.html", job=data, result=None,
                               error=data["error"], active=activo)

    result = data["result"]
    findings = sorted(
        result.findings,
        key=lambda f: (SEVERITY_ORDER[f.severity.value], f.path, f.verdict.value),
    )
    return render_template(
        "report.html",
        job=data,
        job_id=job_id,
        result=result,
        summary=result.summary(),
        findings=findings,
        labels=VERDICT_LABELS,
        bugs=group_repeated(result, data["device"]),
        glossary_errors=[i for i in data["glossary_issues"] if i.level is Level.ERROR],
        por_path=[r for r in by_path(result)
                  if r["errores"] or r["advertencias"] or r["error"]],
        active=activo,
        error=None,
    )


@app.route("/scan/<job_id>/csv")
def job_csv(job_id: str):
    with JOBS_LOCK:
        data = JOBS.get(job_id)
    if data is None or data["state"] != "done":
        return redirect(url_for("home"))

    # utf-8-sig: sin BOM, Excel en Windows rompe los acentos
    contenido = to_csv(data["result"], data["device"]).encode("utf-8-sig")
    return Response(contenido, mimetype="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="qa-{job_id}.csv"'})


@app.route("/scan/<job_id>/report")
def job_html(job_id: str):
    """El reporte en el formato de Test & Feedback que usa el equipo."""
    with JOBS_LOCK:
        data = JOBS.get(job_id)
    if data is None or data["state"] != "done":
        return redirect(url_for("home"))

    contenido = build_html(data["result"], data["device"],
                           TITULOS.get(data["kind"], "QA Report"),
                           started=data["started"], shots=data.get("shots"))
    return Response(contenido, mimetype="text/html; charset=utf-8")


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
        active="glossary",
    )


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
