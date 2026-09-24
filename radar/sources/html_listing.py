"""Config-driven scraper for listing pages that have no API.

National, cantonal, donor and cascade-funding sites are WordPress-ish pages
with no machine interface, and their markup changes without warning. So the
sources live in config/sources.yml as data, and `verify_sources.py` reports
which selectors have stopped matching — a source that silently returns zero
rows is the failure mode that matters here, because it looks like "no calls
this week" instead of "the scraper broke".
"""
from __future__ import annotations

import re
from datetime import date
from urllib.parse import urljoin

from selectolax.parser import HTMLParser

from radar.http import client, retry
from radar.models import Call, parse_date

# Words that mark a link as an actual funding call rather than site furniture.
# Bosnian / Croatian / Serbian plus English.
CALL_WORDS = re.compile(
    r"javni\s+poziv|javni\s+natje[cč]aj|javni\s+oglas|natje[cč]aj|poziv\s+za"
    r"|konkurs|grant|poticaj|potpor|subvenc|sufinancir"
    r"|call\s+for|open\s+call|funding|tender|cascade",
    re.I,
)
# Links that look like calls but are jobs, not money for projects.
NOISE = re.compile(
    r"prijem\s+\w+|radn\w+\s+mjest|popunu\s+|zapo[sš]ljavanj|izbor\s+notara"
    r"|nazo[cč]io|sjednic[ai]|obilje[zž]|posjet|izbor\s+i\s+nominiranje|za\s+izbor\s+"
    r"|pripravnik|vje[zž]benik|namje[sš]tenik|vacancy|recruitment|stru[cč]no\s+osposob"
    r"|imenovanje|razrje[sš]enj|prodaj[au]\s+|licitacij|zakup\s+poslovn",
    re.I,
)
DATE_RX = re.compile(r"(\d{1,2}[.\-/]\d{1,2}[.\-/]\d{4})|(\d{4}-\d{2}-\d{2})")
# Titles that match a call keyword but are not themselves a call to apply to.
NOT_A_CALL = re.compile(
    r"^https?://|^www\.|factsheet|newsletter|privacy|cookie|guidance\s+note"
    r"|frequently\s+asked|obrazac|prijavni\s+obrazac|formular|\.pdf$|^odluka\s+o\s+dodjeli"
    r"|internship|scholarship|traineeship|fellowship|summer\s+school|\bphd\b"
    r"|master\s+thesis|mobility\s+grant|doctoral",
    re.I,
)


def _clean(s: str) -> str:
    return " ".join((s or "").split())


def scrape_source(src: dict, log=print) -> list[Call]:
    """Scrape one configured listing page. Never raises — returns [] and logs."""
    name, url = src["name"], src["url"]
    out: list[Call] = []
    try:
        with client(timeout=src.get("timeout", 45)) as c:
            r = retry(lambda: c.get(url), attempts=2, label=name)
            if r.status_code != 200:
                log(f"  {name}: HTTP {r.status_code} — skipped")
                return []
            tree = HTMLParser(r.text)
    except Exception as e:  # noqa: BLE001
        log(f"  {name}: unreachable ({type(e).__name__}) — skipped")
        return []

    seen = set()
    today = date.today().isoformat()
    for node in tree.css(src.get("link_selector", "a")):
        title = _clean(node.text())
        href = node.attributes.get("href") or ""
        if not href or len(title) < src.get("title_min_len", 25):
            continue
        if src.get("require_call_words", True) and not CALL_WORDS.search(title):
            continue
        if src.get("drop_noise", True) and NOISE.search(title):
            continue
        if NOT_A_CALL.search(title):
            continue
        link = urljoin(url, href)
        if link in seen:
            continue
        seen.add(link)

        m = DATE_RX.search(title)
        out.append(Call(
            source=src["id"],
            source_id=link.rsplit("/", 1)[-1][:90] or link[-90:],
            title=title[:300],
            url=link,
            programme=src.get("programme", name),
            category=src.get("category", "Misc"),
            call_type=src.get("call_type", "national"),
            status="open",              # listing pages carry current calls
            deadline=parse_date(m.group(0)) if m else None,
            countries=src.get("countries", []),
            summary=src.get("note", ""),
            retrieved=today,
            raw_notes=[f"source page: {url}"],
        ))

    limit = src.get("max_items", 60)
    log(f"  {name}: {len(out)} call-like links"
        + (f" (capped at {limit})" if len(out) > limit else ""))
    return out[:limit]


def fetch(sources: list[dict], log=print) -> list[Call]:
    calls: list[Call] = []
    for src in sources:
        if not src.get("enabled", True):
            continue
        calls.extend(scrape_source(src, log=log))
    return calls
