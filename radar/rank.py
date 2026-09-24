"""The four ranking methods, all computed for every call.

The portal lets you switch between them live, so nothing here decides for you.
The default view combines them: gates flag the junk, tier buckets prevent a
huge hard grant outranking easy cash, cash-velocity sorts within a tier.
"""
from __future__ import annotations

import re

from radar.models import Call

# Calls that restrict WHO may apply. These are not judgements about the
# applicant — the tool does not know or assume anything personal. They are
# surfaced so a restriction is never discovered after the work is done.
RESTRICTED = [
    (r"\bwomen\b|\bfemale\b", "restricted to women applicants"),
    (r"\byouth\b|under\s?30|young\s+(researcher|farmer|entrepreneur)", "age-restricted"),
    (r"\bstudent|doctoral|phd\b|post-?doc", "restricted to students or researchers"),
    (r"widening\s+countr|eu-?13\b", "restricted to Widening countries — check BiH status"),
    (r"member\s+states?\s+only|eu\s+member\s+states\s+only", "EU member states only — BiH may be excluded"),
    (r"\bmunicipalit|local\s+authorit|public\s+bod", "restricted to public bodies"),
    (r"\bngo\b|non-?governmental|civil\s+society", "restricted to NGOs or civil society"),
]

# Nationality adjectives that scope a call to one country. Bosnian/Herzegovinian
# are absent on purpose — those are the ones that would INCLUDE this applicant.
NATIONALITIES = (
    "estonian|latvian|lithuanian|polish|czech|slovak|slovenian|croatian|hungarian"
    "|romanian|bulgarian|greek|italian|spanish|portuguese|french|german|austrian"
    "|dutch|belgian|danish|swedish|finnish|norwegian|irish|maltese|cypriot"
    "|serbian|montenegrin|albanian|macedonian|kosovar|turkish|ukrainian|moldovan"
)
# Allow "Slovenian and Croatian SCOs" as well as "Estonian companies": the
# nationality may sit a few words away from the noun it scopes.
ORG_NOUN = (r"compan|sme|sco|cso|ngo|organisation|organization|startup|start-up"
            r"|business|researcher|partner|applicant|entit|institution|firm")
COUNTRY_SCOPED = re.compile(
    rf"\b({NATIONALITIES})\b(?:\s+(?:and|or|,)\s+\w+)?(?:\s+\w+){{0,2}}\s+({ORG_NOUN})",
    re.I)


# ---------------------------------------------------------------- gates
def apply_gates(call: Call, cfg: dict, profile: dict) -> list[str]:
    """Return the list of gates this call FAILS. Flags only, never deletes."""
    g = cfg["gates"]
    failed = []

    if g.get("exclude_closed") and call.status == "closed":
        failed.append("closed")

    d = call.days_to_deadline
    if d is not None and d < 0:
        failed.append("deadline passed")
    elif d is not None and d < g["min_days_to_deadline"]:
        failed.append(f"under {g['min_days_to_deadline']} days left")

    if g.get("exclude_below_min_grant") and call.grant_size is not None:
        if call.grant_size < profile["constraints"]["min_grant_eur"]:
            failed.append("below minimum grant")

    maxp = profile["constraints"]["max_consortium_partners"]
    if call.min_partners and call.min_partners > maxp:
        failed.append(f"needs >{maxp} partners")

    if call.fit_score is not None and call.fit_score < 0.2:
        failed.append("outside capability")

    blob = f"{call.title} {call.summary}".lower()
    for pattern, label in RESTRICTED:
        if re.search(pattern, blob):
            failed.append(label)
            break

    m = COUNTRY_SCOPED.search(blob)
    if m:
        failed.append(f"looks scoped to {m.group(1)} applicants — check eligibility")

    return failed


# ---------------------------------------------------------------- tiers
def tier_of(call: Call, cfg: dict) -> int:
    """1 = easy money, 4 = everything else. Lower is better."""
    t = cfg["tiers"]

    # An unknown grant size cannot qualify as "easy money". Without a figure we
    # have no idea whether there is money in it at all, and letting unknowns
    # into tier 1 lets a scraped factsheet outrank a real multi-million call.
    if call.grant_size is None:
        return 3

    # Easy money you cannot date is not actionable, and a missing deadline is
    # the signature of a scraped link that is not really a call.
    if call.deadline is None:
        return max(3, 2)

    partners = call.min_partners or 1
    upfront = call.upfront_pct or 0.0
    effort = call.effort_days or 999
    ttc = call.time_to_cash_days or 999

    for n in (1, 2, 3):
        c = t[f"t{n}"]
        if (effort <= c["max_effort_days"]
                and upfront >= c["min_upfront_pct"]
                and partners <= c["max_partners"]
                and ttc <= c["max_time_to_cash"]):
            return n
    return 4


# ------------------------------------------------------- cash velocity
def cash_velocity(call: Call) -> tuple[float | None, float | None]:
    """Expected euros per day of your effort, discounted for waiting.

        expected_cash = grant_size x P(win) x prefinancing_%
        time_penalty  = 1 + (days_to_deadline + time_to_cash) / 365
        CVS           = expected_cash / (effort_days x time_penalty)

    Returns (cash_velocity, expected_cash). None when grant size is unknown —
    an unknown is reported as unknown, never defaulted to zero, because a zero
    would sort it alongside genuinely worthless calls.
    """
    if not call.grant_size or not call.effort_days:
        return None, None

    p = call.win_probability or 0.0
    upfront = call.upfront_pct if call.upfront_pct is not None else 0.0
    expected_cash = call.grant_size * p * upfront

    wait = (call.days_to_deadline or 0) + (call.time_to_cash_days or 0)
    penalty = 1 + max(0, wait) / 365
    return expected_cash / (call.effort_days * penalty), expected_cash


RISK_AVERSION = 0.5   # 0 = risk-neutral, 1 = heavily penalise long shots


def cash_velocity_risk(call: Call, raw_cv: float | None) -> float | None:
    """Risk-adjusted cash velocity.

    Raw cash-velocity is risk-NEUTRAL, and that has a consequence worth being
    explicit about: it prefers a 10% shot at a EUR 5M consortium grant over a
    near-certain EUR 80k cascade call, because the expected values say so.

    That arithmetic is right and the conclusion is wrong for a small applicant.
    You cannot run twenty attempts in parallel to let the average arrive; a
    long shot that misses costs real weeks you cannot get back. So we apply a
    concave adjustment, multiplying by p**RISK_AVERSION, which penalises low
    win probabilities far more than high ones.

    Both numbers are kept and both are selectable in the portal, so you can see
    exactly how much the risk view is changing the order.
    """
    if raw_cv is None:
        return None
    p = max(0.0, min(1.0, call.win_probability or 0.0))
    return raw_cv * (p ** RISK_AVERSION)


# ---------------------------------------------------------------- weighted
def weighted_score(call: Call, cfg: dict) -> float:
    """Classic 0-100 rubric, same shape as the second brain's board."""
    w = cfg["weighted"]["weights"]

    size = call.grant_size or 0
    money = (0 if size < 10_000 else 3 if size < 50_000 else 5 if size < 150_000
             else 7 if size < 500_000 else 9 if size < 2_000_000 else 10)

    upfront = (call.upfront_pct or 0) * 10

    effort = call.effort_days or 45
    ease = max(0.0, 10 - (effort / 5))

    probability = (call.win_probability or 0) * 20      # 0.5 -> 10
    fit = (call.fit_score or 0) * 10

    ttc = call.time_to_cash_days or 365
    speed = max(0.0, 10 - (ttc / 40))

    raw = (w["money"] * money + w["upfront"] * upfront + w["ease"] * ease
           + w["probability"] * min(probability, 10) + w["fit"] * fit
           + w["speed"] * speed)
    return round(raw, 1)          # weights sum to 10, factors max 10 -> max 100


# ---------------------------------------------------------------- driver
def rank_all(calls: list[Call], cfg: dict, profile: dict) -> list[Call]:
    for c in calls:
        c.gates_failed = apply_gates(c, cfg, profile)
        c.tier = tier_of(c, cfg)
        c.cash_velocity, c.expected_cash = cash_velocity(c)
        c.cash_velocity_risk = cash_velocity_risk(c, c.cash_velocity)
        c.weighted_score = weighted_score(c, cfg)
    return sort_combined(calls)


def sort_combined(calls: list[Call]) -> list[Call]:
    """Default order: clean calls first, then tier, then cash velocity."""
    return sorted(
        calls,
        key=lambda c: (
            len(c.gates_failed) > 0,
            c.tier or 9,
            -(c.cash_velocity_risk if c.cash_velocity_risk is not None else -1),
        ),
    )
