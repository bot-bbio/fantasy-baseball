"""Tests for the acquisition-budget model."""
from __future__ import annotations

from analysis.budget import AcquisitionBudget, compute_budget

# The real league's settings: 1 acquisition per scoring period (per day), no season cap.
DAILY_SETTINGS = {
    "acquisitionLimit": -1,
    "matchupAcquisitionLimit": 1.0,
    "matchupLimitPerScoringPeriod": True,
}


def test_daily_cap_is_fresh_each_morning():
    """A per-scoring-period cap is treated as unused at run time (the job runs first)."""
    counter = {"acquisitions": 49, "matchupAcquisitionTotals": {"13": 2}}
    budget = compute_budget(DAILY_SETTINGS, counter, matchup_period=13)
    assert budget.period_label == "today"
    assert budget.period_remaining == 1
    assert budget.season_remaining is None      # -1 season limit -> unlimited
    assert budget.remaining == 1
    assert budget.is_capped is True


def test_matchup_period_cap_counts_this_period_usage():
    settings = {
        "acquisitionLimit": -1,
        "matchupAcquisitionLimit": 7,
        "matchupLimitPerScoringPeriod": False,
    }
    counter = {"acquisitions": 49, "matchupAcquisitionTotals": {"13": 5}}
    budget = compute_budget(settings, counter, matchup_period=13)
    assert budget.period_label == "this matchup period"
    assert budget.period_used == 5
    assert budget.period_remaining == 2         # 7 - 5
    assert budget.remaining == 2


def test_season_cap_can_bind():
    settings = {"acquisitionLimit": 60, "matchupAcquisitionLimit": -1}
    counter = {"acquisitions": 58}
    budget = compute_budget(settings, counter, matchup_period=13)
    assert budget.season_remaining == 2
    assert budget.period_remaining is None
    assert budget.remaining == 2


def test_smaller_of_two_caps_wins():
    settings = {
        "acquisitionLimit": 60,
        "matchupAcquisitionLimit": 7,
        "matchupLimitPerScoringPeriod": False,
    }
    counter = {"acquisitions": 59, "matchupAcquisitionTotals": {"4": 1}}
    budget = compute_budget(settings, counter, matchup_period=4)
    assert budget.season_remaining == 1         # binds (smaller than period's 6)
    assert budget.period_remaining == 6
    assert budget.remaining == 1


def test_unlimited_when_no_caps():
    budget = compute_budget({"acquisitionLimit": -1, "matchupAcquisitionLimit": -1}, {}, 1)
    assert budget.remaining is None
    assert budget.is_capped is False
    assert budget.allows(99) is True
    assert "unlimited" in budget.describe()


def test_remaining_never_negative():
    settings = {"acquisitionLimit": 50, "matchupAcquisitionLimit": -1}
    budget = compute_budget(settings, {"acquisitions": 55}, 1)
    assert budget.season_remaining == 0         # clamped, not -5
    assert budget.remaining == 0
    assert budget.allows(1) is False


def test_unlimited_factory():
    budget = AcquisitionBudget.unlimited()
    assert budget.remaining is None
    assert budget.allows(1000) is True
