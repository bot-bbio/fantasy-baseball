"""Tests for the lineup optimizer."""
from __future__ import annotations

import datetime as dt

from analysis.lineup import optimize_lineup
from data.mlb_schedule import ESPN_TO_MLB_ID
from tests.factories import hitter, make_schedule, pitcher

SLOTS = {"C": 1, "1B": 1, "OF": 2, "UTIL": 1, "P": 2, "BE": 3, "IL": 1}


def test_full_lineup_assignment():
    schedule = make_schedule(playing=["NYY", "Bos"], probables={"NYY": "Ace One"})
    roster = [
        hitter(1, "Catcher Guy", team="NYY", slots=("C", "UTIL"), pts=12, slot="C"),
        hitter(2, "Of One", team="NYY", slots=("OF", "UTIL"), pts=30, slot="BE"),
        hitter(3, "Of Two", team="Bos", slots=("OF", "UTIL"), pts=20, slot="BE"),
        hitter(4, "Of Benched", team="Atl", slots=("OF", "UTIL"), pts=18, slot="OF"),  # not playing
        hitter(5, "First Base", team="NYY", slots=("1B", "UTIL"), pts=5, slot="BE"),
        hitter(6, "Util Guy", team="NYY", slots=("UTIL",), pts=8, slot="BE"),
        pitcher(7, "Ace One", team="NYY", slots=("SP", "P"), pts=20, slot="BE"),     # probable
        pitcher(8, "Bench Arm", team="Bos", slots=("SP", "P"), pts=25, slot="BE"),   # not probable
        pitcher(9, "Relief Guy", team="Bos", slots=("RP", "P"), pts=5, slot="BE"),
        hitter(10, "Hurt Guy", team="NYY", slots=("OF", "UTIL", "IL"), pts=40,
               slot="OF", status="OUT", injured=True),
    ]

    plan = optimize_lineup(roster, SLOTS, schedule, is_points=True)
    a = plan.assignments

    assert a[1] == "C"                      # only catcher-eligible
    assert a[5] == "1B"                     # only 1B-eligible
    assert a[2] == "OF" and a[3] == "OF"    # both OF playing
    assert a[6] == "UTIL"
    assert a[7] == "P"                      # probable starter today
    assert a[9] == "P"                      # reliever, team plays
    assert a[8] == "BE"                     # SP not starting today -> bench
    assert a[4] == "BE"                     # team not playing -> bench
    assert a[10] == "IL"                    # injured + IL-eligible -> IL
    assert plan.empty_slots == []


def test_injured_high_value_player_is_not_started():
    schedule = make_schedule(playing=["NYY"])
    roster = [
        hitter(1, "Star Out", team="NYY", slots=("OF", "UTIL", "IL"), pts=99,
               slot="OF", status="OUT", injured=True),
        hitter(2, "Healthy Sub", team="NYY", slots=("OF", "UTIL"), pts=5, slot="BE"),
    ]
    plan = optimize_lineup(roster, {"OF": 1, "BE": 1, "IL": 1}, schedule, is_points=True)
    assert plan.assignments[1] == "IL"
    assert plan.assignments[2] == "OF"


def test_points_ranking_starts_higher_projection():
    schedule = make_schedule(playing=["NYY"])
    roster = [
        hitter(1, "Best", team="NYY", slots=("OF",), pts=30, slot="BE"),
        hitter(2, "Middle", team="NYY", slots=("OF",), pts=25, slot="BE"),
        hitter(3, "Worst", team="NYY", slots=("OF",), pts=20, slot="BE"),
    ]
    plan = optimize_lineup(roster, {"OF": 2, "BE": 1}, schedule, is_points=True)
    assert plan.assignments[1] == "OF"
    assert plan.assignments[2] == "OF"
    assert plan.assignments[3] == "BE"   # lowest projection sits


def test_category_ranking_uses_projected_stats():
    schedule = make_schedule(playing=["NYY"])
    roster = [
        hitter(1, "Slugger", team="NYY", slots=("OF",), pts=0,
               stats={"HR": 40.0, "R": 100.0}),
        hitter(2, "Average", team="NYY", slots=("OF",), pts=0,
               stats={"HR": 20.0, "R": 70.0}),
        hitter(3, "Weak", team="NYY", slots=("OF",), pts=0,
               stats={"HR": 5.0, "R": 40.0}),
    ]
    plan = optimize_lineup(
        roster, {"OF": 2, "BE": 1}, schedule,
        is_points=False, categories=("HR", "R"),
    )
    assert plan.assignments[1] == "OF"
    assert plan.assignments[2] == "OF"
    assert plan.assignments[3] == "BE"


def test_moves_reflect_only_changes():
    schedule = make_schedule(playing=["NYY"], probables={"NYY": "Ace One"})
    roster = [
        hitter(1, "Already Set", team="NYY", slots=("OF",), pts=10, slot="OF"),
        pitcher(2, "Ace One", team="NYY", slots=("SP", "P"), pts=20, slot="BE"),
    ]
    plan = optimize_lineup(roster, {"OF": 1, "P": 1, "BE": 1}, schedule, is_points=True)
    moved_ids = {m.player_id for m in plan.moves}
    assert 1 not in moved_ids          # already in OF, no move
    assert 2 in moved_ids              # BE -> P
    move = next(m for m in plan.moves if m.player_id == 2)
    assert move.from_slot == "BE" and move.to_slot == "P"


def test_unfillable_slot_left_empty():
    schedule = make_schedule(playing=[])  # nobody plays today
    roster = [hitter(1, "Idle", team="NYY", slots=("OF",), pts=10, slot="BE")]
    plan = optimize_lineup(roster, {"OF": 1, "BE": 1}, schedule, is_points=True)
    assert "OF" in plan.empty_slots
    assert plan.assignments[1] == "BE"


def test_locked_player_is_pinned_and_blocks_upgrade():
    # NYY game started an hour ago; Bos hasn't started.
    now = dt.datetime(2026, 6, 20, 20, 0, tzinfo=dt.timezone.utc)
    schedule = make_schedule(playing=["NYY", "Bos"])
    schedule.game_starts[ESPN_TO_MLB_ID["NYY"]] = dt.datetime(2026, 6, 20, 19, 0, tzinfo=dt.timezone.utc)

    roster = [
        hitter(1, "Locked Starter", team="NYY", slots=("OF", "UTIL"), pts=5, slot="OF"),
        hitter(2, "Better Bench", team="Bos", slots=("OF", "UTIL"), pts=50, slot="BE"),
    ]
    plan = optimize_lineup(roster, {"OF": 1, "BE": 1}, schedule, is_points=True, now=now)

    assert plan.assignments[1] == "OF"     # locked -> pinned, not benched
    assert plan.assignments[2] == "BE"     # can't take the locked OF slot
    assert plan.moves == []                # nothing movable
