"""Derive the signals ranking needs from raw call data.

Design rule: every derived number records whether it came from the call itself
or from a default assumption. The UI shows assumed values differently so a
guess is never mistaken for a published figure.
"""
from __future__ import annotations

import re
from radar.models import Call

# Action-type text -> (typical minimum partners, effort bucket).
# Derived from how EU programmes actually structure these instruments.
ACTION_SHAPE = [
    (r"\bCSA\b|coordination and support", 3, "small_consortium"),
    (r"\bRIA\b|research and innovation action", 3, "large_consortium"),
    (r"\bIA\b|innovation action", 3, "large_consortium"),
    (r"cofund|co-fund", 5, "large_consortium"),
    (r"accelerator", 1, "single_beneficiary"),
    (r"\bMSCA\b|marie sk", 1, "single_beneficiary"),
    (r"\bERC\b", 1, "single_beneficiary"),
    (r"lump sum", 1, "single_beneficiary"),
    (r"prize|inducement", 1, "cascade"),
    (r"grant to identified|direct grant", 1, "single_beneficiary"),
    (r"procurement|tender|service contract", 1, "tender"),
    (r"simple grant|project grants|action grant", 2, "single_beneficiary"),
]


def _action_text(call: Call) -> str:
    return " ".join(call.raw_notes + [call.call_type or "", call.deadline_model or ""]).lower()


def _money_floor(size: float | None) -> tuple[int, str] | None:
    """Minimum plausible shape implied by the size of the award alone."""
    if not size:
        return None
    if size >= 3_000_000:
        return 3, "large_consortium"
    if size >= 500_000:
        return 3, "small_consortium"
    if size >= 150_000:
        return 1, "single_beneficiary"
    return None


def _shape(call: Call, effort_cfg: dict) -> tuple[int, str]:
    """Guess (min_partners, effort bucket) from action type AND award size.

    The action name alone is not trustworthy. A real example: Digital Europe
    publishes a EUR 70M award whose action is called "Grants for Procurement",
    which pattern-matches as a tender and would otherwise be scored as a
    15-day solo application. Money is the harder signal, so whichever of the
    two implies more work wins.
    """
    if call.call_type == "cascade":
        regex_shape = (1, "cascade")
    elif call.call_type == "tender":
        regex_shape = (1, "tender")
    else:
        regex_shape = None
        blob = _action_text(call) + " " + call.title.lower()
        for pattern, partners, bucket in ACTION_SHAPE:
            if re.search(pattern, blob):
                regex_shape = (partners, bucket)
                break

    floor = _money_floor(call.grant_size or call.grant_max)

    if regex_shape and floor:
        # Take the more demanding of the two on each axis.
        partners = max(regex_shape[0], floor[0])
        bucket = max(regex_shape[1], floor[1],
                     key=lambda b: effort_cfg.get(b, effort_cfg["unknown"]))
        return partners, bucket
    if regex_shape:
        return regex_shape
    if floor:
        return floor
    return 0, "unknown"


def _grant_size(call: Call) -> tuple[float | None, bool]:
    """Best estimate of what ONE successful applicant receives."""
    if call.grant_max:
        return call.grant_max, False
    if call.budget_total and call.expected_grants and call.expected_grants > 0:
        return call.budget_total / call.expected_grants, True
    if call.grant_min:
        return call.grant_min, False
    if call.budget_total:
        # A whole-call budget is NOT a grant size. Only usable as a weak proxy
        # for small calls where one award is plausible.
        if call.budget_total <= 200_000:
            return call.budget_total, True
        return None, True
    return None, True


# Croatian state programmes aimed explicitly at Croats living in BiH. These
# are the lowest-competition money available to a BiH applicant: the pool is a
# few hundred thousand people rather than all of Europe, and the 2026
# agriculture round alone approved 221 projects.
HR_TO_BIH = re.compile(
    r"hrvat\w*\s+u\s+bosni|hrvate\s+izvan|hrvata\s+izvan|hrvatski\s+narod\s+u\s+bosni"
    r"|iseljeni[sš]tv|croats?\s+(abroad|in\s+bosnia)", re.I)


def _scope(call: Call) -> str:
    """Who may apply. Drives the competition proxy, so keep it conservative."""
    src, blob = call.source, f"{call.title} {call.summary}".lower()

    if HR_TO_BIH.search(blob) or src in ("hr-croats-abroad", "hr-mps-bih"):
        return "bih_croats"
    if src.startswith("hbz-"):
        return "cantonal"
    if src.startswith("fbih-") or call.category == "BiH":
        return "bih_national"
    if src.startswith("hr-") or call.category == "Croatia":
        return "hr_national"
    if call.category == "Interreg":
        return "crossborder"
    if call.call_type == "cascade":
        return "cascade"
    return "eu_wide"


def apply_known(call: Call, known: list[dict]) -> Call:
    """Fill in facts a listing page cannot carry.

    A scraped listing gives a title and a link. Where a programme's size and
    award count have been established from primary reporting, config/
    known_programmes.yml supplies them with a citation. Values already present
    on the call always win — this only fills blanks.
    """
    for prog in known:
        if not re.search(prog["match"], call.title, re.I):
            continue
        for field in ("grant_max", "expected_grants", "scope", "category"):
            if prog.get(field) is not None and getattr(call, field, None) in (None, "Misc"):
                setattr(call, field, prog[field])
        call.raw_notes.append(f"known programme: {prog['name']} — {prog.get('source', '')}")
        break
    return call


def enrich(call: Call, cfg: dict, profile: dict) -> Call:
    cv = cfg["cash_velocity"]
    comp = cfg["competition"]

    size, assumed = _grant_size(call)
    call.grant_size, call.grant_size_assumed = size, assumed

    partners, bucket = _shape(call, cv["effort_days"])
    if call.min_partners is None:
        call.min_partners = partners or None

    call.effort_days = cv["effort_days"].get(bucket, cv["effort_days"]["unknown"])
    call.effort_assumed = True

    # Pre-financing. Lump sum and cascade genuinely pay most of it up front.
    blob = (_action_text(call) + " " + call.title + " " + call.summary).lower()
    is_prize = bool(re.search(r"\bprize\b|inducement prize|award for", blob))
    if is_prize:
        # A prize is paid on award. No co-financing, no reimbursement cycle,
        # no reporting obligations. This is a fact about the instrument, not
        # an assumption, so it is not flagged as one.
        call.upfront_pct = 1.0
        call.upfront_assumed = False
    elif call.call_type == "cascade":
        call.upfront_pct = cv["cascade_prefinancing_pct"]
    elif "lump sum" in blob:
        call.upfront_pct = cv["lump_sum_prefinancing_pct"] * (1 - cv["mutual_insurance_retention"])
    elif call.call_type == "tender":
        call.upfront_pct = 0.0   # tenders pay on delivery, never up front
        call.upfront_assumed = False
    else:
        call.upfront_pct = cv["default_prefinancing_pct"]

    # Time from deadline to cash landing.
    key = ("cascade" if is_prize or call.call_type == "cascade"
           else "tender" if call.call_type == "tender"
           else "two_stage" if (call.deadline_model or "").startswith("two")
           else "single_stage" if call.deadline_model
           else "unknown")
    call.time_to_cash_days = cv["time_to_cash_days"][key]

    # Win probability. Published competition data is rare, so this is a prior
    # adjusted by how many awards the call expects to make.
    p = cv["default_win_probability"]
    if call.expected_grants:
        if call.expected_grants >= 20:
            p = 0.30
        elif call.expected_grants >= 8:
            p = 0.22
        elif call.expected_grants <= 2:
            p = 0.10
    if call.call_type == "cascade":
        p = max(p, 0.25)   # smaller applicant pools
    if is_prize:
        p = 0.05           # one winner, open to all of Europe: be honest
    call.win_probability = p

    # --- competition proxy -------------------------------------------------
    if HR_TO_BIH.search(f"{call.title} {call.summary}"):
        call.category = "HR→BiH"
    call.scope = call.scope or _scope(call)
    call.pool_weight = comp["pool_weight"].get(
        call.scope, comp["pool_weight"][comp["default_scope"]])
    awards = call.expected_grants or 1
    call.odds_proxy = awards / call.pool_weight

    call.fit_score = _fit(call, profile)
    return call


def _fit(call: Call, profile: dict) -> float:
    """0-1: can this applicant actually deliver the work?"""
    cap = profile["capability"]
    blob = f"{call.title} {call.summary} {' '.join(call.keywords)}".lower()

    if any(w in blob for w in cap["weak"]):
        return 0.15
    if call.category == "IT":
        hits = sum(1 for s in cap["strong"] if s in blob)
        return min(1.0, 0.65 + 0.1 * hits)
    if any(s in blob for s in cap["partner_sectors"]):
        return 0.6           # a collaborator's sector, not ours
    return 0.4


def enrich_all(calls: list[Call], cfg: dict, profile: dict,
               known: list[dict] | None = None) -> list[Call]:
    known = known or []
    return [enrich(apply_known(c, known), cfg, profile) for c in calls]
