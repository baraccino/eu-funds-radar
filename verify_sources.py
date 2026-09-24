#!/usr/bin/env python3
"""Check every configured HTML source still parses. Run it when results look thin.

A scraper that silently returns zero rows is indistinguishable from a quiet
week, which is the most dangerous failure mode in a tool like this.
"""
from __future__ import annotations

import pathlib
import sys
import yaml

from radar.sources.cascade import scrape_table
from radar.sources.html_listing import scrape_source
from radar.sources.js_listing import scrape_source as scrape_js

ROOT = pathlib.Path(__file__).resolve().parent


def main() -> int:
    srcs = yaml.safe_load((ROOT / "config/sources.yml").read_text())["sources"]
    print(f"{'source':<26} {'parser':<7} {'marked':<10} {'found':>6}   verdict")
    print("-" * 78)
    broken = 0
    for s in srcs:
        parser = s.get("parser")
        fn = scrape_table if parser == "table" else scrape_js if parser == "js" else scrape_source
        rows = fn(s, log=lambda *a: None)
        marked = "verified" if s.get("verified") else "unverified"
        if rows:
            verdict = "OK" if s.get("verified") else "WORKS — mark verified: true"
        else:
            verdict = "NO MATCHES — fix selector" if s.get("verified") else "no matches"
            if s.get("verified"):
                broken += 1
        print(f"{s['id']:<26} {(s.get('parser') or 'html'):<7} {marked:<10} {len(rows):>6}   {verdict}")
    print("-" * 78)
    if broken:
        print(f"{broken} source(s) marked verified are returning nothing.")
    return 1 if broken else 0


if __name__ == "__main__":
    sys.exit(main())
