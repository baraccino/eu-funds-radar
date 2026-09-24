"""The browser cannot run in every environment, so the parsing logic is tested
as a pure function over the anchors a page would have returned."""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from radar.sources.js_listing import harvest, _available

SRC = {"id": "interreg-danube", "name": "Interreg Danube",
       "url": "https://interreg-danube.eu/calls-for-proposals",
       "category": "Interreg", "call_type": "grant", "programme": "Interreg Danube"}


def test_keeps_real_calls_and_reads_dates():
    rows = harvest([
        {"text": "4th Call for proposals opens 15/11/2026", "href": "https://x/4th-call"},
        {"text": "Open call for Seed Money Facility projects", "href": "https://x/smf"},
    ], SRC)
    assert len(rows) == 2
    assert str(rows[0].deadline) == "2026-11-15"
    assert rows[0].category == "Interreg"


def test_drops_navigation_and_noise():
    rows = harvest([
        {"text": "Frequently asked questions", "href": "https://x/faq"},
        {"text": "Implementation Manual", "href": "https://x/man"},
        {"text": "Javni natječaj za prijem pripravnika", "href": "https://x/job"},
        {"text": "short", "href": "https://x/s"},
    ], SRC)
    assert rows == []


def test_deduplicates_by_href():
    rows = harvest([
        {"text": "Call for proposals number one", "href": "https://x/c1"},
        {"text": "Call for proposals number one again", "href": "https://x/c1"},
    ], SRC)
    assert len(rows) == 1


def test_missing_playwright_is_survivable():
    assert isinstance(_available(), bool)
