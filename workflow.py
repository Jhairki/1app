"""LangChain workflow orchestration for locale verification."""

import json
import logging

from agents.broken_label_detector import run_broken_label_detector
from chains.report_chain import generate_report
from tools.comparator_tool import translation_comparator_tool
from tools.locale_tool import locale_switcher_tool
from tools.scraper_tool import scrape_navigation_tool

logger = logging.getLogger(__name__)


def run_langchain_workflow(base_url: str) -> dict:
    """
    Execute the full LangChain workflow:
    1. Scraper Tool
    2. Locale Switcher Tool
    3. Broken Label Detector Agent
    4. Translation Comparator Tool
    5. Report Generator Chain
    """
    logger.info("Step 1: Scraping navigation links")
    scrape_result = scrape_navigation_tool.invoke({"base_url": base_url})
    scrape_data = json.loads(scrape_result)
    paths = scrape_data["paths"]
    base_url = scrape_data["base_url"]

    logger.info("Step 2: Building Spanish locale URLs")
    locale_result = locale_switcher_tool.invoke({"payload_json": scrape_result})
    locale_data = json.loads(locale_result)
    spanish_urls = locale_data["spanish_urls"]

    logger.info("Step 3: Running broken label detector agent")
    broken_by_path = run_broken_label_detector(base_url, paths, spanish_urls)

    logger.info("Step 4: Comparing translations")
    comparator_input = json.dumps(
        {
            "base_url": base_url,
            "paths": paths,
            "spanish_urls": spanish_urls,
            "broken_by_path": broken_by_path,
        }
    )
    comparator_result = translation_comparator_tool.invoke({"payload_json": comparator_input})

    logger.info("Step 5: Generating report")
    report = generate_report(comparator_result)
    return report
