"""LangChain tool: build Spanish locale URLs."""

import json

from langchain_core.tools import tool

from scraper import build_locale_urls, normalize_base_url


@tool
def locale_switcher_tool(payload_json: str) -> str:
    """
    Append ?locale=es_US to each relative path.
    Input JSON must contain base_url and paths (list of relative paths).
    Returns JSON with base_url, paths, and spanish_urls mapping.
    """
    payload = json.loads(payload_json)
    base_url = normalize_base_url(payload["base_url"])
    paths = payload.get("paths", [])
    spanish_urls = build_locale_urls(base_url, paths, "es_US")
    return json.dumps({"base_url": base_url, "paths": paths, "spanish_urls": spanish_urls})
