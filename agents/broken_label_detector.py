"""LLM-assisted broken label detector agent."""

import json
import logging
import os

from langchain.agents import create_agent
from langchain_core.messages import HumanMessage
from langchain_core.tools import tool
from langchain_google_genai import ChatGoogleGenerativeAI

from scraper import (
    detect_broken_labels_in_links,
    fetch_page_links,
    make_session,
    normalize_base_url,
    RobotsChecker,
)

logger = logging.getLogger(__name__)

DETECTOR_SYSTEM_PROMPT = """You are a localization QA specialist for dealer websites.
Your job is to detect broken Spanish link labels on localized pages.

A label is BROKEN if it:
1. Matches CMS internal key patterns like SITEBUILDER_BUTTONBLOCK_*_LINKTEXT* or SITEBUILDER_*_TEST_*_LINKS*_LINKTEXT*
2. Contains SITEBUILDER or looks like an internal uppercase key with underscores
3. Is clearly not valid Spanish (nonsense, untranslated English placeholders, random codes)

Use the fetch_spanish_page_links tool to load link texts for each path.
Return ONLY valid JSON (no markdown) with this shape:
{"broken_by_path": {"/path": ["broken label 1", "broken label 2"]}}

Include only paths that have at least one broken label. If none found, return {"broken_by_path": {}}.
"""


@tool
def fetch_spanish_page_links(base_url: str, relative_path: str) -> str:
    """
    Fetch all anchor link texts from a Spanish locale page (?locale=es_US).
    Returns JSON with path and links (list of {href, text} objects).
    """
    base_url = normalize_base_url(base_url)
    session = make_session()
    robots = RobotsChecker()
    links = fetch_page_links(base_url, relative_path, "es_US", session, robots)
    return json.dumps(
        {
            "path": relative_path,
            "links": [{"href": link.href, "text": link.text} for link in links],
        }
    )


def _get_llm() -> ChatGoogleGenerativeAI:
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY or GOOGLE_API_KEY must be set in .env")
    return ChatGoogleGenerativeAI(
        model="gemini-2.0-flash",
        google_api_key=api_key,
        temperature=0.2,
    )


def _heuristic_detection(base_url: str, paths: list[str]) -> dict[str, list[str]]:
    """Fallback when LLM is unavailable."""
    base_url = normalize_base_url(base_url)
    session = make_session()
    robots = RobotsChecker()
    broken_by_path: dict[str, list[str]] = {}

    for path in paths:
        links = fetch_page_links(base_url, path, "es_US", session, robots)
        broken = detect_broken_labels_in_links(links)
        if broken:
            broken_by_path[path] = broken

    return broken_by_path


def _parse_agent_output(raw: str) -> dict[str, list[str]]:
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    try:
        data = json.loads(text)
        broken = data.get("broken_by_path", {})
        return {path: labels for path, labels in broken.items() if labels}
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1:
            data = json.loads(text[start : end + 1])
            broken = data.get("broken_by_path", {})
            return {path: labels for path, labels in broken.items() if labels}
    raise ValueError("Agent did not return valid JSON for broken_by_path")


def _extract_agent_text(result: dict) -> str:
    messages = result.get("messages", [])
    if not messages:
        return ""
    last = messages[-1]
    content = getattr(last, "content", last)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
            elif isinstance(block, str):
                parts.append(block)
        return "".join(parts)
    return str(content)


def run_broken_label_detector(
    base_url: str,
    paths: list[str],
    spanish_urls: dict[str, str],
) -> dict[str, list[str]]:
    """
    Run the LLM-assisted broken label detector agent.
    Falls back to heuristic detection when no API key is configured.
    """
    if not paths:
        return {}

    has_key = bool(os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"))
    if not has_key:
        logger.warning("No Gemini API key; using heuristic broken label detection.")
        return _heuristic_detection(base_url, paths)

    tools = [fetch_spanish_page_links]
    llm = _get_llm()
    agent = create_agent(
        model=llm,
        tools=tools,
        system_prompt=DETECTOR_SYSTEM_PROMPT,
        debug=True,
    )

    user_message = (
        f"Base URL: {normalize_base_url(base_url)}\n"
        f"Paths to inspect: {json.dumps(paths)}\n"
        f"Spanish URLs: {json.dumps(spanish_urls)}\n"
        "Inspect each path and return broken_by_path JSON."
    )

    try:
        result = agent.invoke({"messages": [HumanMessage(content=user_message)]})
        output = _extract_agent_text(result)
        return _parse_agent_output(output)
    except Exception as exc:
        logger.exception("Broken label agent failed; falling back to heuristics: %s", exc)
        return _heuristic_detection(base_url, paths)
