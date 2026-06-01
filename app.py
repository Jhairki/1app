"""Flask web interface for LangChain locale verification workflow."""

import logging
import os
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, render_template, request

load_dotenv(Path(__file__).resolve().parent / ".env")

from workflow import run_langchain_workflow

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-key")


def _empty_context(**overrides):
    context = {
        "base_url": "",
        "paths": [],
        "spanish_urls": {},
        "findings": [],
        "summary": None,
        "error": None,
    }
    context.update(overrides)
    return context


@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        base_url = request.form.get("base_url", "").strip()
        if not base_url:
            return render_template("report.html", **_empty_context(error="Please enter a base URL."))

        try:
            logger.info("Starting LangChain workflow for %s", base_url)
            report = run_langchain_workflow(base_url)
            return render_template(
                "report.html",
                base_url=report.get("base_url", base_url),
                paths=report.get("paths", []),
                spanish_urls=report.get("spanish_urls", {}),
                findings=report.get("findings", []),
                summary=report.get("summary"),
                error=None,
            )
        except ValueError as exc:
            return render_template(
                "report.html",
                **_empty_context(base_url=base_url, error=str(exc)),
            )
        except Exception as exc:
            logger.exception("Workflow failed for %s", base_url)
            return render_template(
                "report.html",
                **_empty_context(
                    base_url=base_url,
                    error=f"An unexpected error occurred: {exc}",
                ),
            )

    return render_template("report.html", **_empty_context())


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
