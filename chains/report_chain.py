"""LangChain report generator chain."""

import json
from typing import Any

from langchain_core.runnables import RunnableLambda


def _build_report_payload(data: dict[str, Any]) -> dict[str, Any]:
    findings = data.get("findings", [])
    paths = data.get("paths", [])
    return {
        "base_url": data.get("base_url", ""),
        "paths": paths,
        "spanish_urls": data.get("spanish_urls", {}),
        "findings": findings,
        "summary": {
            "total_paths": len(paths),
            "broken_count": len(findings),
            "affected_pages": len({item["path"] for item in findings}),
        },
    }


report_generator_chain = RunnableLambda(_build_report_payload)


def generate_report(payload_json: str) -> dict[str, Any]:
    """Run the report generator chain on comparator output JSON."""
    data = json.loads(payload_json)
    return report_generator_chain.invoke(data)
