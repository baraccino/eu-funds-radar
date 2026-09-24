#!/usr/bin/env python3
"""Bundle docs/ into a single self-contained page for publishing as an Artifact.

Artifacts supply their own <html>/<head>/<body> skeleton and their CSP blocks
external stylesheets, so the published page inlines CSS and JS. Only
data/calls.json travels alongside — fetching a published file by relative URL
is allowed.

Output: dist/artifact.html  (+ dist/data/calls.json)
"""
from __future__ import annotations

import pathlib
import re
import shutil

ROOT = pathlib.Path(__file__).resolve().parent
DOCS, DIST = ROOT / "docs", ROOT / "dist"

FONTS = (
    '<link rel="preconnect" href="https://fonts.googleapis.com">\n'
    '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>\n'
    '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?'
    'family=IBM+Plex+Sans:wght@400;500;600;700&'
    'family=IBM+Plex+Mono:wght@500;600&display=swap">'
)
# IBM Plex reads as institutional and technical, which suits public-funding
# data; Plex Mono carries the money and per-day figures.
FONT_CSS = """
body{font-family:"IBM Plex Sans",ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif}
.kpi b,.num .big,.meta b,.num .lbl{font-family:"IBM Plex Mono","SF Mono",ui-monospace,Menlo,Consolas,monospace;
  font-variant-numeric:tabular-nums}
h1{font-family:"IBM Plex Mono","SF Mono",ui-monospace,monospace;font-weight:600;letter-spacing:-.02em}
"""


def main() -> int:
    html = (DOCS / "index.html").read_text(encoding="utf-8")
    css = (DOCS / "style.css").read_text(encoding="utf-8")
    js = (DOCS / "app.js").read_text(encoding="utf-8")

    title_m = re.search(r"<title>(.*?)</title>", html, re.S)
    title = title_m.group(1).strip() if title_m else "EU Funds Radar"

    # Keep only what lives inside <body>; the artifact skeleton supplies the rest.
    body_m = re.search(r"<body[^>]*>(.*)</body>", html, re.S)
    if not body_m:
        raise SystemExit("could not find <body> in docs/index.html")
    body = body_m.group(1)
    body = re.sub(r'\s*<script src="app\.js"></script>', "", body)

    page = (
        f"<title>{title}</title>\n{FONTS}\n"
        f"<style>\n{css}\n{FONT_CSS}</style>\n"
        f"{body.strip()}\n"
        f"<script>\n{js}\n</script>\n"
    )

    DIST.mkdir(exist_ok=True)
    (DIST / "artifact.html").write_text(page, encoding="utf-8")
    (DIST / "data").mkdir(exist_ok=True)
    shutil.copy2(DOCS / "data" / "calls.json", DIST / "data" / "calls.json")

    kb = (DIST / "artifact.html").stat().st_size / 1024
    data_kb = (DIST / "data" / "calls.json").stat().st_size / 1024
    print(f"dist/artifact.html      {kb:>8.0f} KB")
    print(f"dist/data/calls.json    {data_kb:>8.0f} KB")

    for bad in ("<!doctype", "<html", "<head>", "<body"):
        if bad in page.lower():
            print(f"WARNING: page still contains {bad}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
