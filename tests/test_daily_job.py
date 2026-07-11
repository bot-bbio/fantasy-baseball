"""Tests for the morning job's budget-aware queue building."""
from __future__ import annotations

from analysis.budget import AcquisitionBudget
from analysis.lineup import LineupPlan, Move
from analysis.streaming import StreamerEvaluation, StreamerRecommendation
from analysis.waivers import Recommendation
from daily_job import build_queue
from pending import ADD_DROP, LINEUP
from tests.factories import hitter, pitcher


def _stream_rec(add_id, add_name, drop_id, drop_name, *, gain=10.0,
                days_out=None, start_label="Today"):
    add = pitcher(add_id, add_name, team="LAD")
    drop = pitcher(drop_id, drop_name, team="NYY")
    ev = StreamerEvaluation(
        player=add, start_day="2026-06-22", opponent="Twins", opponent_ops=0.690,
        park_factor=100, talent=55, form=60, matchup=58, park=50, score=58.0,
        start_label=start_label, days_out=days_out,
    )
    return StreamerRecommendation(ev, drop, gain, drop_is_streamer=False)


def _hitter_rec(add_id, add_name, drop_id, drop_name, *, gain=5.0):
    add = hitter(add_id, add_name, team="Cin")
    drop = hitter(drop_id, drop_name, team="NYY")
    return Recommendation(add, drop, f"Upgrade over {drop_name}", gain)


def _budget(remaining):
    """A budget with a single daily cap, or unlimited when ``remaining`` is None."""
    if remaining is None:
        return AcquisitionBudget.unlimited()
    return AcquisitionBudget(season_used=0, season_limit=None,
                             period_used=0, period_limit=remaining, period_label="today")


def _add_drops(queue):
    return [i for i in queue.items if i.kind == ADD_DROP]


def test_budget_caps_add_drops_and_prefers_pitchers(tmp_path):
    plan = LineupPlan(assignments={})                       # no lineup changes
    streams = [_stream_rec(100, "Stream Ace", 1, "Weak SP"),
               _stream_rec(101, "Stream Two", 2, "Weak SP2")]
    hitters = [_hitter_rec(200, "Hot Bat", 3, "Cold Bat")]

    queue, held = build_queue(plan, streams, hitters, _budget(1),
                              path=tmp_path / "pending.json")

    add_drops = _add_drops(queue)
    assert len(add_drops) == 1                              # only one fits the budget
    assert "Stream Ace" in add_drops[0].description         # pitcher wins the scarce slot
    assert held == 2                                        # two upgrades held back


def test_unlimited_budget_queues_every_upgrade(tmp_path):
    plan = LineupPlan(assignments={})
    streams = [_stream_rec(100, "Stream Ace", 1, "Weak SP")]
    hitters = [_hitter_rec(200, "Hot Bat", 3, "Cold Bat")]

    queue, held = build_queue(plan, streams, hitters, _budget(None),
                              path=tmp_path / "pending.json")

    assert len(_add_drops(queue)) == 2
    assert held == 0


def test_zero_budget_keeps_lineup_but_no_add_drops(tmp_path):
    plan = LineupPlan(assignments={}, moves=[Move(9, "Mover", "SS", "BE")])
    streams = [_stream_rec(100, "Stream Ace", 1, "Weak SP")]
    hitters = [_hitter_rec(200, "Hot Bat", 3, "Cold Bat")]

    queue, held = build_queue(plan, streams, hitters, _budget(0),
                              path=tmp_path / "pending.json")

    kinds = [i.kind for i in queue.items]
    assert kinds == [LINEUP]                                # lineup is free, still queued
    assert _add_drops(queue) == []
    assert held == 2


def test_hitter_used_when_no_streams(tmp_path):
    plan = LineupPlan(assignments={})
    hitters = [_hitter_rec(200, "Hot Bat", 3, "Cold Bat")]

    queue, held = build_queue(plan, [], hitters, _budget(1),
                              path=tmp_path / "pending.json")

    add_drops = _add_drops(queue)
    assert len(add_drops) == 1
    assert "Hot Bat" in add_drops[0].description
    assert held == 0


def test_at_most_one_hitter_is_proposed(tmp_path):
    """MAX_HITTERS keeps offensive churn low even with budget to spare."""
    plan = LineupPlan(assignments={})
    hitters = [_hitter_rec(200, "Bat One", 3, "Cold One"),
               _hitter_rec(201, "Bat Two", 4, "Cold Two")]

    queue, held = build_queue(plan, [], hitters, _budget(None),
                              path=tmp_path / "pending.json")

    assert len(_add_drops(queue)) == 1                      # second hitter never considered
    assert held == 0


def test_far_out_start_is_not_queued(tmp_path):
    """The rolling window surfaces plan-ahead starts, but only imminent ones are queued."""
    plan = LineupPlan(assignments={})
    streams = [_stream_rec(100, "Imminent", 1, "Weak SP", days_out=1, start_label="Tomorrow"),
               _stream_rec(101, "FarOut", 2, "Weak SP2", days_out=4, start_label="Fri Jul 10")]

    queue, _ = build_queue(plan, streams, [], _budget(None),
                           path=tmp_path / "pending.json")

    add_drops = _add_drops(queue)
    assert len(add_drops) == 1                              # far-out start is not queued
    assert "Imminent" in add_drops[0].description
    assert all("FarOut" not in i.description for i in add_drops)


def test_queued_stream_description_shows_start_date(tmp_path):
    plan = LineupPlan(assignments={})
    streams = [_stream_rec(100, "Stream Ace", 1, "Weak SP", days_out=0, start_label="Today")]

    queue, _ = build_queue(plan, streams, [], _budget(None),
                           path=tmp_path / "pending.json")

    assert "starts Today" in _add_drops(queue)[0].description
