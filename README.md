# Locale Link Verifier

A Flask-based web interface for a LangChain workflow that verifies Spanish locale navigation labels on dealer websites.

## Overview

This project scrapes navigation links from a dealer website, generates Spanish locale URLs, detects broken Spanish labels in localized pages, compares them to English labels, and produces a report. It can use a Gemini/Google Generative AI model for smarter broken-label detection, with a heuristic fallback when no API key is available.

## Features

- Scrapes navigation links from a base URL using `div.header-navigation` or `<nav>`.
- Builds Spanish locale URLs by appending `?locale=es_US` to each path.
- Detects broken Spanish link texts in the localized pages.
- Compares broken Spanish labels to English page labels via `?locale=en_US`.
- Looks up expected Spanish translations from `translations.csv`.
- Renders a summary report in a browser using Flask.

## Architecture

- `app.py` - Flask application and web UI.
- `workflow.py` - Orchestrates the scan pipeline.
- `scraper.py` - Scrapes navigation links, builds locale URLs, fetches pages, and performs broken label detection and comparison.
- `tools/scraper_tool.py` - LangChain tool for scraping navigation links.
- `tools/locale_tool.py` - LangChain tool for generating Spanish locale URLs.
- `tools/comparator_tool.py` - LangChain tool for comparing broken labels against English labels and translations.
- `agents/broken_label_detector.py` - LLM-assisted agent for detecting broken Spanish page labels, with fallback heuristic logic.
- `chains/report_chain.py` - Generates the final report payload.
- `templates/report.html` - HTML template for the web report.
- `translations.csv` - English-to-Spanish translation reference.

## Requirements

Install the Python dependencies:

```bash
python -m pip install -r requirements.txt
```

## Environment

Create a `.env` file in the project root to configure optional secrets and settings:

```env
SECRET_KEY=your-secret-key
GEMINI_API_KEY=your_gemini_api_key
# or
GOOGLE_API_KEY=your_google_api_key
```

- `SECRET_KEY` is used by Flask for session security.
- `GEMINI_API_KEY` or `GOOGLE_API_KEY` enables the LLM-assisted broken label detector.

If no API key is present, the project uses a heuristic detector based on text patterns.

## Usage

1. Install dependencies.
2. Ensure `.env` is configured if you want LLM support.
3. Run the app:

```bash
python app.py
```

4. Open the browser at `http://localhost:5000`.
5. Enter the dealer site base URL and submit the form.

## Behavior

- The app scrapes navigation links from the given base URL.
- It then creates Spanish locale page URLs and inspects each localized page for broken labels.
- Broken labels are compared to the matching English page text and translation lookup entries.
- The report displays:
  - total navigation paths
  - affected pages
  - broken label count
  - broken text, English label, and expected Spanish translation

## Notes

- Navigation scraping prefers `div.header-navigation`, then falls back to `<nav>`.
- Relative links are normalized and external domains are ignored.
- Translation lookup uses `translations.csv`; missing file is handled gracefully.

## Troubleshooting

- If no navigation links are found, verify the URL and page structure.
- If you see `ValueError` for missing API keys, add `GEMINI_API_KEY` or `GOOGLE_API_KEY` to `.env`.
- The current locale switching approach is query-parameter based (`?locale=es_US` / `?locale=en_US`).

## License

This repository does not include a license file. Add one if you intend to share or publish the code.
