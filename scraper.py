"""Scraping, locale verification, and translation comparison utilities."""

import csv
import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urljoin, urlparse, urlunparse, parse_qs, urlencode
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

REQUEST_DELAY_SECONDS = 1.0
REQUEST_TIMEOUT_SECONDS = 30
USER_AGENT = "LocaleVerifierBot/1.0 (+https://github.com/locale-verifier)"
RESPECT_ROBOTS_TXT = False
DEFAULT_TRANSLATIONS_FILE = Path(__file__).resolve().parent / "translations.csv"

BROKEN_LABEL_PATTERNS = [
    re.compile(r"SITEBUILDER_BUTTONBLOCK_.*_LINKTEXT", re.IGNORECASE),
    re.compile(r"SITEBUILDER_.*_TEST_.*_LINKS.*_LINKTEXT", re.IGNORECASE),
]

SPANISH_HINT_PATTERN = re.compile(
    r"[áéíóúñüÁÉÍÓÚÑÜ]|(\b(de|la|el|en|y|para|con|por|un|una|los|las|del|al)\b)",
    re.IGNORECASE,
)


@dataclass
class LinkInfo:
    href: str
    text: str


@dataclass
class BrokenFinding:
    path: str
    broken_text: str
    english_text: str = ""
    expected_spanish: str = ""


@dataclass
class ScanReport:
    base_url: str
    paths: list[str] = field(default_factory=list)
    spanish_urls: dict[str, str] = field(default_factory=dict)
    english_urls: dict[str, str] = field(default_factory=dict)
    findings: list[BrokenFinding] = field(default_factory=list)


class RobotsChecker:
    """Cache robots.txt rules per origin."""

    def __init__(self):
        self._parsers: dict[str, RobotFileParser | _PermissiveRobotParser] = {}

    def can_fetch(self, url: str) -> bool:
        parsed = urlparse(url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        if origin not in self._parsers:
            robots_url = urljoin(origin, "/robots.txt")
            parser = RobotFileParser()
            parser.set_url(robots_url)
            try:
                parser.read()
                logger.info("Loaded robots.txt from %s", robots_url)
            except Exception as exc:
                logger.warning("Could not read robots.txt at %s: %s", robots_url, exc)
                parser = _PermissiveRobotParser()
            self._parsers[origin] = parser
        return self._parsers[origin].can_fetch(USER_AGENT, url)


class _PermissiveRobotParser:
    def can_fetch(self, _user_agent: str, _url: str) -> bool:
        return True


def normalize_base_url(url: str) -> str:
    url = url.strip()
    if not url:
        raise ValueError("Base URL is required.")
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    if not url.endswith("/"):
        url += "/"
    return url


def make_session() -> requests.Session:
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    return session


def fetch_page(
    session: requests.Session,
    url: str,
    robots: RobotsChecker,
) -> str | None:
    if RESPECT_ROBOTS_TXT and not robots.can_fetch(url):
        logger.warning("Blocked by robots.txt: %s", url)
        return None
    try:
        response = session.get(url, timeout=REQUEST_TIMEOUT_SECONDS)
        response.raise_for_status()
        return response.text
    except requests.RequestException as exc:
        logger.error("Failed to fetch %s: %s", url, exc)
        return None


def find_navigation(soup: BeautifulSoup):
    header_nav = soup.find("div", class_="header-navigation")
    if header_nav:
        logger.info("Found navigation in div.header-navigation")
        return header_nav
    nav = soup.find("nav")
    if nav:
        logger.info("Found navigation in <nav> element")
        return nav
    logger.warning("No navigation element found")
    return None


def to_relative_path(base_url: str, href: str) -> str | None:
    if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
        return None
    absolute = urljoin(base_url, href)
    base_parsed = urlparse(base_url)
    link_parsed = urlparse(absolute)
    if link_parsed.netloc and link_parsed.netloc != base_parsed.netloc:
        return None
    path = link_parsed.path or "/"
    if not path.startswith("/"):
        path = "/" + path
    return path


def scrape_navigation_links(
    base_url: str,
    session: requests.Session | None = None,
    robots: RobotsChecker | None = None,
) -> list[str]:
    base_url = normalize_base_url(base_url)
    robots = robots or RobotsChecker()
    session = session or make_session()

    html = fetch_page(session, base_url, robots)
    if html is None:
        return []

    soup = BeautifulSoup(html, "html.parser")
    navigation = find_navigation(soup)
    if navigation is None:
        return []

    paths: list[str] = []
    seen: set[str] = set()
    for anchor in navigation.find_all("a", href=True):
        relative = to_relative_path(base_url, anchor["href"])
        if relative and relative not in seen:
            seen.add(relative)
            paths.append(relative)
            logger.debug("Found link: %s", relative)

    logger.info("Scraped %d unique relative paths from %s", len(paths), base_url)
    return paths


def append_locale_param(base_url: str, relative_path: str, locale: str) -> str:
    absolute = urljoin(base_url, relative_path)
    parsed = urlparse(absolute)
    query = parse_qs(parsed.query, keep_blank_values=True)
    query["locale"] = [locale]
    new_query = urlencode(query, doseq=True)
    return urlunparse(parsed._replace(query=new_query))


def build_locale_urls(
    base_url: str,
    relative_paths: list[str],
    locale: str,
) -> dict[str, str]:
    base_url = normalize_base_url(base_url)
    return {path: append_locale_param(base_url, path, locale) for path in relative_paths}


def extract_links_from_html(html: str, base_url: str) -> list[LinkInfo]:
    soup = BeautifulSoup(html, "html.parser")
    links: list[LinkInfo] = []
    seen: set[tuple[str, str]] = set()
    for anchor in soup.find_all("a", href=True):
        href = anchor["href"].strip()
        text = anchor.get_text(strip=True)
        if not text:
            continue
        relative = to_relative_path(base_url, href) or href
        key = (relative, text)
        if key in seen:
            continue
        seen.add(key)
        links.append(LinkInfo(href=relative, text=text))
    return links


def fetch_page_links(
    base_url: str,
    relative_path: str,
    locale: str,
    session: requests.Session,
    robots: RobotsChecker,
) -> list[LinkInfo]:
    url = append_locale_param(base_url, relative_path, locale)
    html = fetch_page(session, url, robots)
    if html is None:
        return []
    return extract_links_from_html(html, base_url)


def matches_broken_pattern(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return False
    return any(pattern.search(stripped) for pattern in BROKEN_LABEL_PATTERNS)


def looks_like_nonsense_spanish(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return False
    if matches_broken_pattern(stripped):
        return True
    if "SITEBUILDER" in stripped.upper():
        return True
    if re.fullmatch(r"[A-Z0-9_\-]+", stripped) and len(stripped) > 8:
        return True
    if "_" in stripped and stripped.upper() == stripped and not SPANISH_HINT_PATTERN.search(stripped):
        return True
    return False


def detect_broken_labels_in_links(links: list[LinkInfo]) -> list[str]:
    broken: list[str] = []
    seen: set[str] = set()
    for link in links:
        if looks_like_nonsense_spanish(link.text) and link.text not in seen:
            seen.add(link.text)
            broken.append(link.text)
    return broken


def load_translation_map(csv_path: str | Path | None = None) -> dict[str, str]:
    path = Path(csv_path) if csv_path else DEFAULT_TRANSLATIONS_FILE
    translations: dict[str, str] = {}
    if not path.exists():
        logger.warning("Translation file not found: %s", path)
        return translations

    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            english = (row.get("English") or row.get("english") or "").strip()
            spanish = (row.get("Spanish") or row.get("spanish") or "").strip()
            if english and spanish:
                translations[english] = spanish

    logger.info("Loaded %d translation entries from %s", len(translations), path)
    return translations


def lookup_translation(english_text: str, translations: dict[str, str]) -> str:
    if not english_text:
        return ""
    if english_text in translations:
        return translations[english_text]
    lowered = english_text.lower()
    for key, value in translations.items():
        if key.lower() == lowered:
            return value
    return ""


def find_english_text_for_broken(
    broken_text: str,
    spanish_links: list[LinkInfo],
    english_links: list[LinkInfo],
) -> str:
    spanish_by_href = {link.href: link.text for link in spanish_links}
    english_by_href = {link.href: link.text for link in english_links}

    for href, text in spanish_by_href.items():
        if text == broken_text and href in english_by_href:
            return english_by_href[href]

    spanish_index = next((i for i, link in enumerate(spanish_links) if link.text == broken_text), None)
    if spanish_index is not None and spanish_index < len(english_links):
        return english_links[spanish_index].text

    return ""


def compare_broken_labels(
    base_url: str,
    broken_by_path: dict[str, list[str]],
    session: requests.Session,
    robots: RobotsChecker,
    translations: dict[str, str] | None = None,
) -> list[BrokenFinding]:
    base_url = normalize_base_url(base_url)
    translations = translations or load_translation_map()
    findings: list[BrokenFinding] = []

    for index, (path, broken_labels) in enumerate(broken_by_path.items()):
        if index > 0:
            time.sleep(REQUEST_DELAY_SECONDS)

        spanish_links = fetch_page_links(base_url, path, "es_US", session, robots)
        english_links = fetch_page_links(base_url, path, "en_US", session, robots)

        for broken_text in broken_labels:
            english_text = find_english_text_for_broken(broken_text, spanish_links, english_links)
            expected_spanish = lookup_translation(english_text, translations)
            findings.append(
                BrokenFinding(
                    path=path,
                    broken_text=broken_text,
                    english_text=english_text,
                    expected_spanish=expected_spanish,
                )
            )

    return findings


def scan_spanish_pages_for_broken_labels(
    base_url: str,
    relative_paths: list[str],
    session: requests.Session | None = None,
    robots: RobotsChecker | None = None,
) -> dict[str, list[str]]:
    base_url = normalize_base_url(base_url)
    session = session or make_session()
    robots = robots or RobotsChecker()
    results: dict[str, list[str]] = {}

    for index, path in enumerate(relative_paths):
        if index > 0:
            time.sleep(REQUEST_DELAY_SECONDS)

        logger.info("Scanning Spanish labels at %s", append_locale_param(base_url, path, "es_US"))
        links = fetch_page_links(base_url, path, "es_US", session, robots)
        broken = detect_broken_labels_in_links(links)
        if broken:
            results[path] = broken
            logger.warning("Broken labels on %s: %s", path, broken)

    return results


def run_deterministic_scan(base_url: str) -> ScanReport:
    """Run the full pipeline without the LLM agent (heuristic detection only)."""
    base_url = normalize_base_url(base_url)
    session = make_session()
    robots = RobotsChecker()
    translations = load_translation_map()

    paths = scrape_navigation_links(base_url, session=session, robots=robots)
    spanish_urls = build_locale_urls(base_url, paths, "es_US")
    english_urls = build_locale_urls(base_url, paths, "en_US")

    if paths:
        time.sleep(REQUEST_DELAY_SECONDS)

    broken_by_path = scan_spanish_pages_for_broken_labels(
        base_url, paths, session=session, robots=robots
    )
    findings = compare_broken_labels(
        base_url, broken_by_path, session, robots, translations
    )

    return ScanReport(
        base_url=base_url,
        paths=paths,
        spanish_urls=spanish_urls,
        english_urls=english_urls,
        findings=findings,
    )
