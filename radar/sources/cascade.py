"""Cascade funding / FSTP calls — the "easy money" layer.

Cascade sub-calls are NOT in the EU Funding & Tenders Portal API. Verified:
querying SEDIA for the Horizon Europe framework programme returns the parent
research calls, not the sub-calls those projects later publish. Each funded
project runs its own open call on its own website, so the only practical index
is a curated aggregator.

This reads Kaila's cascade-funding roundup, which publishes a table of open
calls with up to five deadline columns. Rows whose deadlines have all passed
are dropped — the page keeps historical entries alongside live ones.

Grant size: these tables do not publish amounts. Rather than leave every
cascade call unranked, we apply the standard Horizon Europe FSTP ceiling of
EUR 60,000 per third party as a conservative default, flagged as an estimate.
Call conditions can raise it, so treat it as a floor for comparison, not a
promise. See the Commission's "Good practices for implementing FSTP in EU
grants" and NCP Flanders' cascade-funding infosheet.
"""
from __future__ import annotations

import re
from datetime import date

from selectolax.parser import HTMLParser

from radar.http import client, retry
from radar.models import Call, parse_date
from radar.sources.html_listing import NOT_A_CALL

DATE_CELL = re.compile(r"\d{1,2}[./-]\d{1,2}[./-]\d{4}")


def _clean(s: str) -> str:
    return " ".join((s or "").split())


def scrape_table(src: dict, log=print) -> list[Call]:
    url = src["url"]
    try:
        with client(timeout=src.get("timeout", 45)) as c:
            r = retry(lambda: c.get(url), attempts=2, label=src["name"])
            if r.status_code != 200:
                log(f"  {src['name']}: HTTP {r.status_code} — skipped")
                return []
            tree = HTMLParser(r.text)
    except Exception as e:  # noqa: BLE001
        log(f"  {src['name']}: unreachable ({type(e).__name__}) — skipped")
        return []

    today = date.today()
    out: list[Call] = []
    stale = 0

    for table in tree.css("table"):
        for row in table.css("tr"):
            cells = row.css("td")
            if len(cells) < 2:
                continue                      # header or layout row
            title = _clean(cells[0].text())
            if len(title) < 10 or NOT_A_CALL.search(title):
                continue

            # Collect every date in the row; the live deadline is the earliest
            # one still in the future.
            future = []
            for cell in cells[1:]:
                txt = _clean(cell.text())
                for m in DATE_CELL.finditer(txt):
                    d = parse_date(m.group(0))
                    if d and d >= today:
                        future.append(d)
            if not future:
                stale += 1
                continue

            link = row.css_first("a")
            href = (link.attributes.get("href") if link else None) or url

            out.append(Call(
                source=src["id"],
                source_id=re.sub(r"\W+", "-", title.lower())[:80],
                title=title[:300],
                url=href,
                programme=src.get("programme", "Cascade / FSTP"),
                category=src.get("category", "IT"),
                call_type="cascade",
                status="open",
                deadline=min(future),
                deadline_model="single-stage",
                grant_max=src.get("assumed_grant_eur"),
                summary=src.get("note", ""),
                retrieved=today.isoformat(),
                raw_notes=[
                    f"source page: {url}",
                    "grant size assumed at the standard FSTP ceiling; confirm in the call",
                ],
            ))

    log(f"  {src['name']}: {len(out)} live cascade calls ({stale} past-deadline rows dropped)")
    return out[:src.get("max_items", 120)]


def fetch(sources: list[dict], log=print) -> list[Call]:
    calls: list[Call] = []
    for src in sources:
        if src.get("enabled", True) and src.get("parser") == "table":
            calls.extend(scrape_table(src, log=log))
    return calls
