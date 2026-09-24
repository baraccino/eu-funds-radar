# EU Funds Radar

A weekly-refreshed, ranked board of EU and BiH funding calls, tuned for one question:

> **Which of these gets money into my account fastest, for the least work?**

Static site, no server, no database. GitHub Actions scrapes on Mondays, commits the data, GitHub Pages serves it.

---

## What it does

1. **Pulls** from the official EU Funding & Tenders Portal API plus configured national, cantonal, Interreg and cascade-funding sources.
2. **Enriches** each call — grant size, how much is paid up front, days of effort, time until cash lands, win probability, capability fit.
3. **Ranks** it four different ways, all computed, switchable live in the UI.
4. **Flags** anything you probably can't or shouldn't apply for, without deleting it.
5. **Commits** the result and redeploys the page.

---

## The four ranking methods

All four are computed for every call. Switch between them in the **Rank by** dropdown.

| Method | What it answers |
|---|---|
| **Combined** (default) | Flagged calls last → tier → risk-adjusted €/day. |
| **Cash velocity (risk-adjusted)** | Expected € per day of your effort, penalising long shots. |
| **Cash velocity (raw)** | Same, risk-neutral. Deliberately favours big grants with low odds. |
| **Weighted 0–100** | Classic rubric: money, upfront, ease, odds, fit, speed. |
| **Tier** | 1 = lump sum, paid up front, solo applicant, fast. 4 = everything else. |

### Cash velocity

```
expected_cash = grant_size × P(win) × prefinancing_%
time_penalty  = 1 + (days_to_deadline + time_to_cash) / 365
CVS           = expected_cash / (effort_days × time_penalty)
```

**Why there are two versions.** Raw cash velocity is risk-neutral, and that has a consequence worth seeing: it prefers a 10% shot at a €5M consortium grant over a near-certain €80k cascade call, because the expected values say so. The arithmetic is right; the conclusion is wrong for a small applicant, because you can't run twenty attempts in parallel and let the average arrive. The risk-adjusted version multiplies by `p^0.5`, which penalises low win probabilities much harder. Both are shown so you can see how much the risk view moves things.

### Tiers

Tier 1 is the "easy money" bucket: effort ≤ 6 days, ≥ 60% paid up front, solo applicant, cash within 120 days. **A call with an unknown grant size can never be tier 1** — without a figure there's no way to know there's money in it, and letting unknowns in lets a scraped factsheet outrank a real call.

Retune all of it in `config/ranking.yml`. Nothing is hardcoded.

---

## Honesty rules

This tool feeds real financial decisions, so:

- **Nothing is invented.** An unknown grant size is `null` and renders as `—`, never as a plausible-looking guess.
- **Derived numbers are marked `est`** in the UI. Effort days, win probability and most pre-financing rates are estimates. Grant sizes taken straight from the call are not.
- **Facts are not flagged as estimates.** A prize pays 100% on award and a tender pays 0% up front — those are properties of the instrument, so they're marked as known.
- **Gates flag, they never delete.** Tick *Show flagged calls* to see everything.
- **Source health is on the page.** A scraper returning zero looks exactly like a quiet week, which is the failure mode that matters most here.

### Known limitations

- **Applicant restrictions are detected by keyword**, from the title and summary only. A restriction that only appears in the call PDF will be missed. *Always read the call document before investing time.*
- **Win probability is a prior**, adjusted by how many awards a call expects to make. Real competition ratios are rarely published.
- **Effort estimates are heuristics** from the instrument type and award size, not from reading the application pack.
- **Cascade funding coverage is thin.** It's the highest-value category and the worst-indexed — each funded project publishes its own call on its own site. Adding good cascade sources is the single biggest improvement available.

---

## Running it

```bash
pip install -r requirements.txt
python run.py                 # scrape, enrich, rank -> docs/data/calls.json
python -m pytest tests/ -q    # 19 tests
python verify_sources.py      # which scrapers still parse?
cd docs && python -m http.server 8000
```

## Adding a source

Sources are data, not code. Add a block to `config/sources.yml`:

```yaml
  - id: my-source
    name: "Some ministry"
    url: "https://example.gov.ba/calls/"
    link_selector: "h2 a"
    category: BiH          # IT | Misc | BiH | Interreg
    call_type: national
    verified: false
```

Then run `python verify_sources.py` — it reports which selectors match and which have rotted. Mark `verified: true` once it returns rows, so the tool can tell "broken" from "quiet".

## Project layout

```
config/       profile, ranking weights, source definitions  <- tune here
radar/        models, enrichment, ranking, sources
docs/         the static site (GitHub Pages root)
tests/        19 tests, run in CI before every scrape
run.py        the weekly pipeline
```

## Notes on the SEDIA API

Learned from the live endpoint, not the docs:

- POST `multipart/form-data`, every part typed `application/json`.
- The query DSL is a narrow Elasticsearch subset: `terms` works, `prefix` returns 400, and **`range` is silently ignored** — a server-side date filter looks applied but isn't, so date filtering must happen locally.
- Every metadata value is wrapped in a list.
- `budgetOverview` is a list containing a JSON *string* that needs parsing again. It carries `expectedGrants`, `minContribution` and `maxContribution`.
- Status codes: `31094501` forthcoming, `31094502` open, `31094503` closed.

---

## Setup

1. Push to a GitHub repo.
2. **Settings → Pages → Source: GitHub Actions.**
3. **Settings → Actions → General → Workflow permissions: Read and write.**
4. Actions tab → *Weekly funding scan* → **Run workflow** to seed it.

It then runs every Monday at 06:00 UTC.
