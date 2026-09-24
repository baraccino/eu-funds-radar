"""Normalised shape every source must produce."""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field, asdict
from datetime import date, datetime
from typing import Any

ISO = "%Y-%m-%d"


def _parse_date(v: Any) -> date | None:
    """Accept the several date shapes the sources emit. Never guess."""
    if v in (None, "", []):
        return None
    if isinstance(v, list):
        v = v[0] if v else None
        if v is None:
            return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    s = str(v).strip()
    # SEDIA: 2026-09-24T00:00:00.000+0000
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        try:
            return date(int(m[1]), int(m[2]), int(m[3]))
        except ValueError:
            return None
    # dd.mm.yyyy — common on BiH and regional sites
    m = re.match(r"(\d{1,2})[.\-/](\d{1,2})[.\-/](\d{4})", s)
    if m:
        try:
            return date(int(m[3]), int(m[2]), int(m[1]))
        except ValueError:
            return None
    return None


@dataclass
class Call:
    """One funding opportunity, from any source.

    Money fields are euros. A value of None means *unknown* and is rendered as
    such — it is never silently replaced with a plausible-looking number.
    """

    # identity
    source: str
    source_id: str
    title: str
    url: str

    # classification
    programme: str | None = None
    category: str = "Misc"           # IT | Misc | BiH | Interreg
    call_type: str | None = None     # grant | tender | cascade | national
    status: str | None = None        # open | forthcoming | closed

    # dates
    opens: date | None = None
    deadline: date | None = None
    deadline_model: str | None = None   # single-stage | two-stage

    # money (euros; None = unknown)
    budget_total: float | None = None
    grant_min: float | None = None
    grant_max: float | None = None
    expected_grants: int | None = None

    # applicant shape
    min_partners: int | None = None
    countries: list[str] = field(default_factory=list)

    # free text
    summary: str = ""
    keywords: list[str] = field(default_factory=list)

    # provenance — every record must be traceable
    retrieved: str = ""
    raw_notes: list[str] = field(default_factory=list)

    # ---- filled in by enrich.py ----
    grant_size: float | None = None
    grant_size_assumed: bool = False
    upfront_pct: float | None = None
    upfront_assumed: bool = True
    effort_days: float | None = None
    effort_assumed: bool = True
    time_to_cash_days: int | None = None
    win_probability: float | None = None
    win_probability_assumed: bool = True
    fit_score: float | None = None

    # ---- filled in by rank.py ----
    gates_failed: list[str] = field(default_factory=list)
    tier: int | None = None
    cash_velocity: float | None = None
    cash_velocity_risk: float | None = None
    weighted_score: float | None = None
    expected_cash: float | None = None

    @property
    def uid(self) -> str:
        return hashlib.sha1(f"{self.source}:{self.source_id}".encode()).hexdigest()[:16]

    @property
    def days_to_deadline(self) -> int | None:
        if not self.deadline:
            return None
        return (self.deadline - date.today()).days

    def to_json(self) -> dict:
        d = asdict(self)
        for k in ("opens", "deadline"):
            d[k] = d[k].isoformat() if d[k] else None
        d["uid"] = self.uid
        d["days_to_deadline"] = self.days_to_deadline
        return d


def parse_date(v: Any) -> date | None:
    return _parse_date(v)
