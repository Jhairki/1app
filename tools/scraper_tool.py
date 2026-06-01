"""LangChain tool: scrape navigation links from a dealer site."""

import json

from langchain_core.tools import tool

from scraper import normalize_base_url, scrape_navigation_links


@tool
def scrape_navigation_tool(base_url: str) -> str:
    """
    Scrape relative navigation link paths from a dealer website.
    Looks for div.header-navigation first, then falls back to nav.
    Returns JSON with base_url and paths (list of relative paths).
    """
    normalized = normalize_base_url(base_url)
    paths = scrape_navigation_links(normalized)
    return json.dumps({"base_url": normalized, "paths": paths})
