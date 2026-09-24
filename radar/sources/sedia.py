"""EU Funding & Tenders Portal — official SEDIA Search API.

Verified against the live API on 2026-09-24.

Notes learned from the real endpoint, not from documentation:
  * Request body must be multipart/form-data, each part typed application/json.
  * The query DSL is a narrow Elasticsearch subset: `terms` works, `prefix`
    returns HTTP 400, and `range` is SILENTLY IGNORED. So date filtering must
    happen locally — a server-side range filter looks like it worked and isn't
    applied, which would quietly drop calls.
  * Every metadata value is wrapped in a list.
  * `budgetOverview` is a list containing a JSON *string* that must be parsed
    a second time. It carries expectedGrants / minContribution / maxContribution.
  * Status codes: 31094501 Forthcoming, 31094502 Open, 31094503 Closed.
"""
from __future__ import annotations

import json
from datetime import date, datetime

from radar.http import client, retry
from radar.models import Call, parse_date

API = "https://api.tech.ec.europa.eu/search-api/prod/rest/search"
STATUS = {"31094501": "forthcoming", "31094502": "open", "31094503": "closed"}
LIVE_STATUSES = ["31094501", "31094502"]
PAGE_SIZE = 100

# Programme derived from the identifier prefix — self-evident from the data and
# stable, unlike the numeric frameworkProgramme codes which the facet API does
# not resolve to names.
PROGRAMME = {
    "HORIZON": "Horizon Europe",
    "DIGITAL": "Digital Europe",
    "ERASMUS": "Erasmus+",
    "CREA": "Creative Europe",
    "CERV": "Citizens, Equality, Rights and Values",
    "SMP": "Single Market Programme",
    "LIFE": "LIFE",
    "EU4H": "EU4Health",
    "ISF": "Internal Security Fund",
    "AMIF": "Asylum, Migration and Integration Fund",
    "EDF": "European Defence Fund",
    "CEF": "Connecting Europe Facility",
    "EURATOM": "Euratom",
    "EUBA": "EU Bodies / Agencies",
    "JUST": "Justice Programme",
    "IPA": "IPA III",
    "RESTORE": "Restore our Ocean and Waters",
}

# Which capability bucket a call most likely needs. Used for categorisation.
IT_HINTS = (
    "digital", "software", "data", "ai", "artificial intelligence", "cloud",
    "cyber", "platform", "ict", "computing", "internet", "app", "algorithm",
    "interoperab", "blockchain", "semantic", "web",
)


def _one(md: dict, key: str, default=None):
    v = md.get(key, default)
    if isinstance(v, list):
        return v[0] if v else default
    return v


def _budget(md: dict) -> dict:
    """Unwrap the double-encoded budgetOverview blob. Returns {} if absent."""
    raw = md.get("budgetOverview")
    if isinstance(raw, list):
        raw = raw[0] if raw else None
    if not raw:
        return {}
    try:
        blob = json.loads(raw) if isinstance(raw, str) else raw
    except (json.JSONDecodeError, TypeError):
        return {}
    actions = []
    for entries in (blob.get("budgetTopicActionMap") or {}).values():
        if isinstance(entries, list):
            actions.extend(entries)
    if not actions:
        return {}
    a = actions[0]
    total = 0.0
    for v in (a.get("budgetYearMap") or {}).values():
        try:
            total += float(v)
        except (TypeError, ValueError):
            pass
    out = {}
    if total > 0:
        out["budget_total"] = total
    for src, dst in (("expectedGrants", "expected_grants"),
                     ("minContribution", "grant_min"),
                     ("maxContribution", "grant_max")):
        try:
            val = float(a.get(src) or 0)
        except (TypeError, ValueError):
            val = 0
        if val > 0:
            out[dst] = int(val) if dst == "expected_grants" else val
    if a.get("deadlineModel"):
        out["deadline_model"] = a["deadlineModel"]
    return out


def _categorise(title: str, summary: str, keywords: list[str]) -> str:
    blob = f"{title} {summary} {' '.join(keywords)}".lower()
    return "IT" if any(h in blob for h in IT_HINTS) else "Misc"


def fetch(max_pages: int = 30, log=print) -> list[Call]:
    query = {
        "bool": {
            "must": [
                {"terms": {"type": ["1", "2", "8"]}},
                {"terms": {"status": LIVE_STATUSES}},
            ]
        }
    }
    calls: list[Call] = []
    today = date.today().isoformat()

    with client() as c:
        page = 1
        total = None
        while page <= max_pages:
            def go(p=page):
                return c.post(
                    API,
                    params={"apiKey": "SEDIA", "text": "***",
                            "pageSize": PAGE_SIZE, "pageNumber": p},
                    files={
                        "query": (None, json.dumps(query), "application/json"),
                        "languages": (None, json.dumps(["en"]), "application/json"),
                    },
                )

            r = retry(go, label=f"SEDIA page {page}")
            if r.status_code != 200:
                raise RuntimeError(f"SEDIA page {page}: HTTP {r.status_code}")
            data = r.json()
            if total is None:
                total = data.get("totalResults", 0)
                log(f"  SEDIA: {total} live records")
            results = data.get("results") or []
            if not results:
                break

            for res in results:
                md = res.get("metadata") or {}
                ident = _one(md, "identifier") or _one(md, "callIdentifier") or res.get("reference")
                if not ident:
                    continue
                title = _one(md, "title") or ""
                summary = (res.get("summary") or "").strip()
                kws = md.get("keywords") or []
                if isinstance(kws, str):
                    kws = [kws]
                b = _budget(md)
                status_code = str(_one(md, "status") or "")
                call = Call(
                    source="sedia",
                    source_id=str(ident),
                    title=title.strip(),
                    url=res.get("url") or "",
                    programme=PROGRAMME.get(str(ident).split("-")[0].upper(),
                                            str(ident).split("-")[0]),
                    category=_categorise(title, summary, [str(k) for k in kws]),
                    call_type="tender" if _one(md, "type") == "2" else "grant",
                    status=STATUS.get(status_code),
                    opens=parse_date(_one(md, "startDate")),
                    deadline=parse_date(_one(md, "deadlineDate")),
                    deadline_model=b.get("deadline_model") or _one(md, "deadlineModel"),
                    budget_total=b.get("budget_total"),
                    grant_min=b.get("grant_min"),
                    grant_max=b.get("grant_max"),
                    expected_grants=b.get("expected_grants"),
                    summary=summary[:600],
                    keywords=[str(k) for k in kws][:12],
                    retrieved=today,
                )
                if _one(md, "typesOfAction"):
                    call.raw_notes.append(f"action: {_one(md, 'typesOfAction')}")
                calls.append(call)

            if total and page * PAGE_SIZE >= total:
                break
            page += 1

    log(f"  SEDIA: parsed {len(calls)} calls")
    return calls
