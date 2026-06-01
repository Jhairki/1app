"""LangChain tool: compare broken labels with English pages and translations CSV."""

import json

from langchain_core.tools import tool

from scraper import (
    BrokenFinding,
    compare_broken_labels,
    load_translation_map,
    make_session,
    normalize_base_url,
    RobotsChecker,
)


@tool
def translation_comparator_tool(payload_json: str) -> str:
    """
    Compare broken Spanish labels against English pages (?locale=en_US)
    and look up expected Spanish translations in translations.csv.
    Input JSON: base_url, paths, broken_by_path (dict path -> list of broken texts).
    Returns JSON with findings (path, broken_text, english_text, expected_spanish).
    """
    payload = json.loads(payload_json)
    base_url = normalize_base_url(payload["base_url"])
    broken_by_path = payload.get("broken_by_path", {})
    session = make_session()
    robots = RobotsChecker()
    translations = load_translation_map()
    findings = compare_broken_labels(
        base_url, broken_by_path, session, robots, translations
    )
    return json.dumps(
        {
            "base_url": base_url,
            "paths": payload.get("paths", []),
            "spanish_urls": payload.get("spanish_urls", {}),
            "findings": [
                {
                    "path": item.path,
                    "broken_text": item.broken_text,
                    "english_text": item.english_text,
                    "expected_spanish": item.expected_spanish,
                }
                for item in findings
            ],
        }
    )
