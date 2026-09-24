"""Scraper for listing pages whose content is rendered by JavaScript.

Some programmes ship an empty HTML shell and fetch their call list in the
browser. Interreg Danube is one: its calls page returns 60 KB of markup with
about 3,700 characters of visible text, essentially all navigation, and no
JSON endpoint or framework payload to read instead. A real browser is the only
way in.

Playwright is therefore an OPTIONAL dependency. If it is missing, or no
browser is installed, this returns an empty list and says so rather than
raising — a browser problem must never take the rest of the weekly scan down.

Set PLAYWRIGHT_CHROMIUM_PATH to use a specific binary (needed where the
bundled browser version does not match the installed one).
"""
from __future__ import annotations

import os
import re
from datetime import date

from radar.models import Call, parse_date
from radar.sources.html_listing import CALL_WORDS, NOISE, NOT_A_CALL

DATE_RX = re.compile(r"(\d{1,2}[.\-/]\d{1,2}[.\-/]\d{4})|(\d{4}-\d{2}-\d{2})")

# Runs inside the page. Returns every anchor with usable text.
EXTRACT = """() => [...document.querySelectorAll('a')]
  .map(a => ({ text: (a.innerText || a.textContent || '').trim().replace(/\\s+/g, ' '),
               href: a.href }))
  .filter(x => x.text.length > 15 && x.href)"""


def _available():
    try:
        from playwright.sync_api import sync_playwright  # noqa: F401
        return True
    except ImportError:
        return False


def harvest(anchors: list[dict], src: dict) -> list[Call]:
    """Turn raw anchors into Calls. Pure function — unit-testable without a browser."""
    today = date.today()
    out, seen = [], set()
    for a in anchors:
        title, href = (a.get("text") or "").strip(), a.get("href") or ""
        if len(title) < src.get("title_min_len", 22) or not href:
            continue
        if src.get("require_call_words", True) and not CALL_WORDS.search(title):
            continue
        if NOISE.search(title) or NOT_A_CALL.search(title):
            continue
        if href in seen:
            continue
        seen.add(href)
        m = DATE_RX.search(title)
        out.append(Call(
            source=src["id"],
            source_id=href.rsplit("/", 1)[-1][:90] or href[-90:],
            title=title[:300],
            url=href,
            programme=src.get("programme", src["name"]),
            category=src.get("category", "Misc"),
            call_type=src.get("call_type", "grant"),
            status="open",
            deadline=parse_date(m.group(0)) if m else None,
            countries=src.get("countries", []),
            summary=src.get("note", ""),
            retrieved=today.isoformat(),
            raw_notes=[f"source page: {src['url']} (JavaScript-rendered)"],
        ))
    return out[:src.get("max_items", 60)]


def scrape_source(src: dict, log=print) -> list[Call]:
    if not _available():
        log(f"  {src['name']}: playwright not installed — skipped")
        return []
    from playwright.sync_api import sync_playwright

    launch = {}
    if os.environ.get("PLAYWRIGHT_CHROMIUM_PATH"):
        launch["executable_path"] = os.environ["PLAYWRIGHT_CHROMIUM_PATH"]

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(**launch)
            page = browser.new_page(user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120 Safari/537.36"))
            try:
                page.goto(src["url"], wait_until="networkidle",
                          timeout=src.get("timeout_ms", 45000))
                page.wait_for_timeout(src.get("settle_ms", 2500))
                anchors = page.evaluate(EXTRACT)
            finally:
                browser.close()
    except Exception as e:  # noqa: BLE001
        log(f"  {src['name']}: browser failed ({type(e).__name__}) — skipped")
        return []

    calls = harvest(anchors, src)
    log(f"  {src['name']}: {len(calls)} call-like links (rendered)")
    return calls


def fetch(sources: list[dict], log=print) -> list[Call]:
    calls: list[Call] = []
    for src in sources:
        if src.get("enabled", True) and src.get("parser") == "js":
            calls.extend(scrape_source(src, log=log))
    return calls
