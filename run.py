#!/usr/bin/env python3
"""Weekly pipeline: fetch -> enrich -> rank -> write docs/data/calls.json

Run locally:   python run.py
In CI:         .github/workflows/scrape.yml (Mondays 06:00 UTC)

Failure policy: one broken source must never wipe the dataset. Sources that
fail are logged and reported in the output payload, and the previous data for
that source is carried forward so the portal degrades instead of emptying.
"""
from __future__ import annotations

import json
import pathlib
import sys
import traceback
from datetime import datetime, timezone

import yaml

from radar.enrich import enrich_all
from radar.rank import rank_all
from radar.sources import cascade, html_listing, js_listing, sedia

ROOT = pathlib.Path(__file__).resolve().parent
OUT = ROOT / "docs" / "data" / "calls.json"


def log(*a):
    print(*a, flush=True)


def load_previous() -> dict:
    if OUT.exists():
        try:
            return json.loads(OUT.read_text())
        except json.JSONDecodeError:
            return {}
    return {}


def main() -> int:
    cfg = yaml.safe_load((ROOT / "config/ranking.yml").read_text())
    profile = yaml.safe_load((ROOT / "config/profile.yml").read_text())
    sources_cfg = yaml.safe_load((ROOT / "config/sources.yml").read_text())["sources"]

    previous = load_previous()
    prev_calls = previous.get("calls", [])
    calls, errors = [], []

    log("Fetching sources")

    # --- EU Funding & Tenders Portal (official API) ---
    try:
        calls.extend(sedia.fetch(log=log))
    except Exception as e:  # noqa: BLE001
        errors.append({"source": "sedia", "error": f"{type(e).__name__}: {e}"})
        log(f"  SEDIA FAILED: {e}")
        carried = [c for c in prev_calls if c.get("source") == "sedia"]
        log(f"  carrying forward {len(carried)} previous SEDIA calls")
        calls.extend(_revive(carried))

    # --- HTML listing sources ---
    try:
        calls.extend(html_listing.fetch(
            [s for s in sources_cfg if not s.get("parser")], log=log))
    except Exception as e:  # noqa: BLE001
        errors.append({"source": "html", "error": f"{type(e).__name__}: {e}"})
        log(f"  HTML sources FAILED: {e}")

    # --- JavaScript-rendered listings (optional; needs playwright) ---
    try:
        calls.extend(js_listing.fetch(sources_cfg, log=log))
    except Exception as e:  # noqa: BLE001
        errors.append({"source": "js", "error": f"{type(e).__name__}: {e}"})
        log(f"  JS sources FAILED: {e}")

    # --- cascade / FSTP tables (the easy-money layer) ---
    try:
        calls.extend(cascade.fetch(sources_cfg, log=log))
    except Exception as e:  # noqa: BLE001
        errors.append({"source": "cascade", "error": f"{type(e).__name__}: {e}"})
        log(f"  Cascade sources FAILED: {e}")

    if not calls:
        log("ABORT: zero calls fetched; refusing to overwrite good data")
        return 1

    # --- dedupe by uid, preferring the richer record ---
    by_uid: dict[str, object] = {}
    for c in calls:
        cur = by_uid.get(c.uid)
        if cur is None or (c.grant_size or 0) > (getattr(cur, "grant_size", 0) or 0):
            by_uid[c.uid] = c
    calls = list(by_uid.values())

    log(f"\nEnriching and ranking {len(calls)} calls")
    calls = enrich_all(calls, cfg, profile)
    calls = rank_all(calls, cfg, profile)

    clean = [c for c in calls if not c.gates_failed]
    tier1 = [c for c in clean if c.tier == 1]
    log(f"  {len(clean)} pass all gates | {len(tier1)} in tier 1 (easy money)")

    payload = {
        "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "counts": {
            "total": len(calls),
            "passing_gates": len(clean),
            "tier1": len(tier1),
            "by_category": {
                k: sum(1 for c in calls if c.category == k)
                for k in ("IT", "Misc", "BiH", "Interreg")
            },
        },
        "sources": [
            {"id": s["id"], "name": s["name"], "verified": bool(s.get("verified")),
             "count": sum(1 for c in calls if c.source == s["id"])}
            for s in sources_cfg
        ] + [{"id": "sedia", "name": "EU Funding & Tenders Portal",
              "verified": True,
              "count": sum(1 for c in calls if c.source == "sedia")}],
        "errors": errors,
        "config": {"ranking": cfg, "profile_constraints": profile["constraints"]},
        "calls": [c.to_json() for c in calls],
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=1))
    size_kb = OUT.stat().st_size / 1024
    log(f"\nWrote {OUT.relative_to(ROOT)} ({size_kb:.0f} KB)")
    if errors:
        log(f"WARNING: {len(errors)} source(s) failed — see 'errors' in payload")
    return 0


def _revive(rows: list[dict]):
    """Rebuild Call objects from a previous run's JSON."""
    from radar.models import Call, parse_date
    out = []
    for r in rows:
        r = dict(r)
        for k in ("uid", "days_to_deadline"):
            r.pop(k, None)
        for k in ("opens", "deadline"):
            r[k] = parse_date(r.get(k))
        try:
            out.append(Call(**r))
        except TypeError:
            continue
    return out


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        traceback.print_exc()
        sys.exit(1)
