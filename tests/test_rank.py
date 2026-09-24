import sys, pathlib, datetime
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import yaml
from radar.models import Call
from radar.enrich import enrich
from radar.rank import (apply_gates, tier_of, cash_velocity, cash_velocity_risk,
                        weighted_score, sort_combined)

ROOT = pathlib.Path(__file__).resolve().parents[1]
CFG = yaml.safe_load((ROOT / "config/ranking.yml").read_text())
PROF = yaml.safe_load((ROOT / "config/profile.yml").read_text())
TODAY = datetime.date.today()


def mk(**kw):
    base = dict(source="t", source_id="x", title="t", url="u",
                deadline=TODAY + datetime.timedelta(days=60))
    base.update(kw)
    return Call(**base)


def test_cascade_beats_giant_consortium():
    """The whole point: easy money must outrank big hard money."""
    easy = enrich(mk(source_id="easy", title="cascade open call",
                     call_type="cascade", grant_max=80_000), CFG, PROF)
    huge = enrich(mk(source_id="huge", title="RIA research and innovation action",
                     grant_max=5_000_000, expected_grants=2), CFG, PROF)
    for c in (easy, huge):
        c.tier = tier_of(c, CFG)
        c.cash_velocity, c.expected_cash = cash_velocity(c)
        c.cash_velocity_risk = cash_velocity_risk(c, c.cash_velocity)
        c.gates_failed = apply_gates(c, CFG, PROF)

    # Tiering is what enforces "easy money".
    assert easy.tier == 1 and huge.tier == 4

    # Documented behaviour: RAW cash-velocity is risk-neutral and genuinely
    # prefers the big consortium grant. This is not a bug, it is the metric.
    assert huge.cash_velocity > easy.cash_velocity

    # Risk adjustment reverses it, which is what a small applicant needs.
    assert easy.cash_velocity_risk > huge.cash_velocity_risk

    # The combined default sort puts easy money on top either way.
    assert sort_combined([huge, easy])[0].source_id == "easy"


def test_unknown_grant_size_is_none_not_zero():
    c = enrich(mk(title="mystery"), CFG, PROF)
    cv, cash = cash_velocity(c)
    assert c.grant_size is None
    assert cv is None and cash is None


def test_tender_gets_no_upfront():
    c = enrich(mk(call_type="tender", grant_max=100_000), CFG, PROF)
    assert c.upfront_pct == 0.0
    assert c.upfront_assumed is False
    cv, cash = cash_velocity(c)
    assert cash == 0.0


def test_gate_flags_expired_deadline():
    c = enrich(mk(deadline=TODAY - datetime.timedelta(days=3), grant_max=50_000), CFG, PROF)
    assert "deadline passed" in apply_gates(c, CFG, PROF)


def test_gate_flags_out_of_capability():
    c = enrich(mk(title="quantum computing hardware", summary="quantum", grant_max=90_000), CFG, PROF)
    assert c.fit_score == 0.15
    assert "outside capability" in apply_gates(c, CFG, PROF)


def test_weighted_score_bounded():
    for size in (0, 5_000, 90_000, 9_000_000):
        c = enrich(mk(grant_max=size or None), CFG, PROF)
        s = weighted_score(c, CFG)
        assert 0 <= s <= 100, (size, s)


def test_budget_over_expected_grants_is_flagged_assumed():
    c = enrich(mk(budget_total=10_000_000, expected_grants=5), CFG, PROF)
    assert c.grant_size == 2_000_000
    assert c.grant_size_assumed is True


def test_whole_call_budget_not_used_as_grant_size_when_large():
    c = enrich(mk(budget_total=40_000_000), CFG, PROF)
    assert c.grant_size is None, "must not treat a whole-call budget as one grant"


def test_gates_flag_but_do_not_delete():
    calls = [enrich(mk(source_id=str(i), grant_max=50_000), CFG, PROF) for i in range(3)]
    calls[1].deadline = TODAY - datetime.timedelta(days=1)
    for c in calls:
        c.gates_failed = apply_gates(c, CFG, PROF)
        c.tier = tier_of(c, CFG); c.cash_velocity, _ = cash_velocity(c)
    out = sort_combined(calls)
    assert len(out) == 3, "gated calls must remain in the list"
    assert out[-1].source_id == "1", "gated call sorts last"


def test_unknown_grant_size_cannot_reach_tier_1():
    """A scraped factsheet with no money attached must not outrank a real call."""
    junk = enrich(mk(source_id="junk", title="cascade open call",
                     call_type="cascade"), CFG, PROF)          # no grant size
    real = enrich(mk(source_id="real", title="cascade open call",
                     call_type="cascade", grant_max=90_000), CFG, PROF)
    for c in (junk, real):
        c.tier = tier_of(c, CFG)
        c.cash_velocity, _ = cash_velocity(c)
        c.cash_velocity_risk = cash_velocity_risk(c, c.cash_velocity)
        c.gates_failed = apply_gates(c, CFG, PROF)
    assert junk.grant_size is None
    assert junk.tier >= 3, "unknown value must not be tier 1"
    assert real.tier == 1
    assert sort_combined([junk, real])[0].source_id == "real"


def test_huge_award_is_never_a_quick_solo_job():
    """Real case: Digital Europe's EUR 70M 'Grants for Procurement' action
    pattern-matches as a tender. Money must override the action name."""
    c = enrich(mk(title="AI compute evaluation and deployment platform",
                  grant_max=70_000_000, expected_grants=1,
                  raw_notes=["action: DIGITAL JU Grants for Procurement"]), CFG, PROF)
    c.tier = tier_of(c, CFG)
    assert c.effort_days >= 45, f"70M treated as {c.effort_days}d of work"
    assert c.min_partners >= 3
    assert c.tier == 4, f"70M consortium landed in tier {c.tier}"


def test_small_cascade_keeps_low_effort():
    c = enrich(mk(title="cascade open call", call_type="cascade",
                  grant_max=60_000), CFG, PROF)
    assert c.effort_days == 4
    assert tier_of(c, CFG) == 1


def test_prize_pays_in_full_and_is_not_flagged_as_assumed():
    c = enrich(mk(title="The European Prize for Women Innovators",
                  grant_max=50_000), CFG, PROF)
    assert c.upfront_pct == 1.0
    assert c.upfront_assumed is False, "prize payout is a fact, not an assumption"
    assert c.win_probability == 0.05, "prizes are lottery-like; must not be flattered"
    assert tier_of(c, CFG) == 1


def test_restricted_calls_are_flagged_not_silently_ranked():
    """The prize for Women Innovators ranked #1 before this gate existed.
    The tool must surface the restriction rather than assume anything."""
    c = enrich(mk(title="The European Prize for Women Innovators",
                  grant_max=50_000), CFG, PROF)
    flags = apply_gates(c, CFG, PROF)
    assert any("women" in f for f in flags), flags


def test_restriction_flag_does_not_delete_the_call():
    c = enrich(mk(title="Prize for Women Innovators", grant_max=50_000), CFG, PROF)
    c.gates_failed = apply_gates(c, CFG, PROF)
    c.tier = tier_of(c, CFG); c.cash_velocity, _ = cash_velocity(c)
    c.cash_velocity_risk = cash_velocity_risk(c, c.cash_velocity)
    assert len(sort_combined([c])) == 1, "flagged calls stay visible behind a toggle"


def test_unrestricted_call_is_not_flagged():
    c = enrich(mk(title="Digital innovation deployment platform", grant_max=200_000), CFG, PROF)
    assert not any("restricted" in f for f in apply_gates(c, CFG, PROF))


def test_cascade_without_deadline_cannot_be_tier_1():
    c = enrich(mk(title="some cascade call", call_type="cascade",
                  grant_max=60_000, deadline=None), CFG, PROF)
    assert tier_of(c, CFG) >= 2, "an undateable call is not actionable"


def test_country_scoped_call_is_flagged():
    c = enrich(mk(title="Innovation Funding for Estonian Cybersecurity Companies",
                  grant_max=60_000), CFG, PROF)
    flags = apply_gates(c, CFG, PROF)
    assert any("estonian" in f.lower() for f in flags), flags


def test_bih_relevant_call_is_not_country_flagged():
    for title in ["Open call for SMEs across Europe",
                  "AI4Gov-X Cascade Funding Call",
                  "Support for Bosnian companies"]:
        c = enrich(mk(title=title, grant_max=60_000), CFG, PROF)
        assert not any("scoped to" in f for f in apply_gates(c, CFG, PROF)), title


def test_multi_country_scope_is_caught():
    c = enrich(mk(title="Call for proposal for support to Slovenian and Croatian SCOs",
                  grant_max=60_000), CFG, PROF)
    assert any("scoped to" in f for f in apply_gates(c, CFG, PROF))


# ---------------------------------------------------------- new filters
def test_grants_over_one_million_are_gated_out():
    c = enrich(mk(title="Huge consortium call", grant_max=5_000_000), CFG, PROF)
    flags = apply_gates(c, CFG, PROF)
    assert any("cap" in f for f in flags), flags


def test_grant_just_under_the_cap_survives():
    c = enrich(mk(title="Sensible sized call", grant_max=950_000), CFG, PROF)
    assert not any("cap" in f for f in apply_gates(c, CFG, PROF))


def test_croatian_programme_for_bih_is_recategorised_and_low_competition():
    c = enrich(mk(title="Javni poziv za potpore poljoprivrednim projektima Hrvata u Bosni i Hercegovini",
                  grant_max=100_000, expected_grants=221), CFG, PROF)
    assert c.category == "HR→BiH"
    assert c.scope == "bih_croats"
    assert c.pool_weight == 3
    assert c.odds_proxy > 70


def test_easiest_ranking_prefers_many_awards_in_a_small_pool():
    from radar.rank import easiest_score
    local = enrich(mk(title="Javni poziv Hrvata u Bosni i Hercegovini",
                      grant_max=100_000, expected_grants=221), CFG, PROF)
    euwide = enrich(mk(title="Pan-European innovation action",
                       grant_max=900_000, expected_grants=3), CFG, PROF)
    for c in (local, euwide):
        c.easiest_score = easiest_score(c)
    assert local.easiest_score > euwide.easiest_score
    assert 0 <= euwide.easiest_score <= 100


def test_cantonal_call_is_the_smallest_pool():
    c = enrich(mk(source="hbz-mpvs", title="Javni poziv za potporu mladim poljoprivrednicima",
                  grant_max=20_000), CFG, PROF)
    assert c.scope == "cantonal"
    assert c.pool_weight == 1


def test_eu_wide_is_the_default_scope():
    c = enrich(mk(source="sedia", title="Research and innovation action", grant_max=800_000), CFG, PROF)
    assert c.scope == "eu_wide"
    assert c.pool_weight == 100


def test_known_programme_facts_fill_blanks_only():
    import yaml as _y
    from radar.enrich import apply_known
    known = _y.safe_load((ROOT / "config/known_programmes.yml").read_text())["programmes"]

    c = apply_known(mk(title="Javni poziv za dodjelu potpora razvoju poljoprivrednih "
                             "projekata Hrvata u Bosni i Hercegovini za 2026."), known)
    assert c.expected_grants == 221
    assert c.grant_max == 100_000
    assert c.category == "HR→BiH"
    assert any("known programme" in n for n in c.raw_notes)


def test_known_programme_never_overwrites_scraped_values():
    import yaml as _y
    from radar.enrich import apply_known
    known = _y.safe_load((ROOT / "config/known_programmes.yml").read_text())["programmes"]
    c = apply_known(mk(title="potpore poljoprivrednim projektima Hrvata u Bosni i Hercegovini",
                       grant_max=55_000, expected_grants=9), known)
    assert c.grant_max == 55_000, "a real scraped figure must win over the stored one"
    assert c.expected_grants == 9


def test_cap_also_catches_huge_calls_with_unpublished_award_size():
    """The cap used to keep exactly the calls it could not measure: an unknown
    size can never exceed a ceiling, so 95M MSCA calls sailed through."""
    c = enrich(mk(title="MSCA Staff Exchanges 2027", budget_total=95_000_000), CFG, PROF)
    assert c.grant_size is None
    flags = apply_gates(c, CFG, PROF)
    assert any("unpublished" in f for f in flags), flags


def test_small_call_with_unknown_award_size_is_kept():
    c = enrich(mk(title="Javni poziv za potporu", budget_total=200_000), CFG, PROF)
    assert not any("unpublished" in f for f in apply_gates(c, CFG, PROF))


def test_call_with_no_budget_at_all_is_kept():
    """Cantonal and Croatian listings publish no figures; they must survive."""
    c = enrich(mk(source="hbz-mpvs", title="Javni poziv za potporu mladim poljoprivrednicima"), CFG, PROF)
    assert c.grant_size is None and c.budget_total is None
    assert not any("cap" in f or "unpublished" in f for f in apply_gates(c, CFG, PROF))
