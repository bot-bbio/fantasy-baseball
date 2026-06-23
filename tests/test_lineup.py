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


def test_rest_day_starter_stays_parked_no_churn():
    """The reported bug: on a rest day, don't bench an idle starter and slide an
    already-active player into the vacated slot -- that's churn with zero gain."""
    schedule = make_schedule(playing=["NYY"])   # only NYY plays; Adames' team (Mil) is off
    roster = [
        hitter(1, "Willy Adames", team="Mil", slots=("SS", "UTIL"), pts=30, slot="SS"),
        hitter(2, "Jose Caballero", team="NYY", slots=("OF", "SS", "UTIL"), pts=10, slot="OF"),
    ]
    slots = {"SS": 1, "OF": 1, "UTIL": 1, "BE": 2, "IL": 1}
    plan = optimize_lineup(roster, slots, schedule, is_points=True)
    assert plan.assignments[1] == "SS"    # idle SS stays parked, not benched
    assert plan.assignments[2] == "OF"    # already-active OF is not churned into SS
    assert plan.moves == []               # nothing to do today


def test_starting_pitcher_kept_between_starts():
    """A rostered SP not pitching today stays in the SP slot -- don't churn the rotation."""
    schedule = make_schedule(playing=["NYY"])   # NYY plays, but our SP isn't probable today
    roster = [pitcher(1, "Core Ace", team="NYY", slots=("SP", "P"), pts=40, slot="SP")]
    plan = optimize_lineup(roster, {"SP": 1, "BE": 1}, schedule, is_points=True)
    assert plan.assignments[1] == "SP"
    assert plan.moves == []


def test_playing_bench_player_still_replaces_resting_incumbent():
    """The soft target must not block a *real* upgrade: a benched player who plays today
    takes the slot of an incumbent whose team is off."""
    schedule = make_schedule(playing=["NYY"])   # incumbent's team (Mil) off; sub's team plays
    roster = [
        hitter(1, "Resting Incumbent", team="Mil", slots=("SS",), pts=30, slot="SS"),
        hitter(2, "Playing Sub", team="NYY", slots=("SS",), pts=10, slot="BE"),
    ]
    plan = optimize_lineup(roster, {"SS": 1, "BE": 2}, schedule, is_points=True)
    assert plan.assignments[2] == "SS"    # plays today -> started
    assert plan.assignments[1] == "BE"    # slot genuinely needed, so the idle one sits


def _ohtani(slot="UTIL"):
    # Two-way: eligible to hit (UTIL/DH) and pitch (P/SP).
    return hitter(1, "Shohei Ohtani", team="LAD", slots=("DH", "UTIL", "P", "SP"),
                  pts=15, slot=slot, position="DH")


def test_ohtani_rule_moves_two_way_starter_to_the_mound():
    """On a start day, a two-way player is slotted to pitch and a bench bat fills his UTIL."""
    schedule = make_schedule(playing=["LAD"], probables={"LAD": "Shohei Ohtani"})
    roster = [
        _ohtani(slot="UTIL"),
        hitter(2, "Bench Bat", team="LAD", slots=("UTIL", "OF"), pts=8, slot="BE"),
    ]
    slots = {"UTIL": 1, "P": 1, "BE": 2, "IL": 1}
    plan = optimize_lineup(roster, slots, schedule, is_points=True)
    assert plan.assignments[1] == "P"        # Ohtani pitches today
    assert plan.assignments[2] == "UTIL"     # bench bat backfills his slot
    assert plan.two_way_pitching == ["Shohei Ohtani"]
    assert "bench" in plan.two_way_prompt().lower()


def test_ohtani_rule_flags_open_util_when_no_bench_bat():
    """If no bench hitter can fill UTIL, it's left open and the prompt points to a pickup."""
    schedule = make_schedule(playing=["LAD"], probables={"LAD": "Shohei Ohtani"})
    roster = [_ohtani(slot="UTIL")]          # nobody to backfill UTIL
    slots = {"UTIL": 1, "P": 1, "BE": 2, "IL": 1}
    plan = optimize_lineup(roster, slots, schedule, is_points=True)
    assert plan.assignments[1] == "P"
    assert "UTIL" in plan.empty_slots
    assert "add a hitter" in plan.two_way_prompt().lower()


def test_ohtani_stays_a_hitter_when_not_pitching():
    """On a non-start day he keeps hitting -- the rule only fires when he's the probable SP."""
    schedule = make_schedule(playing=["LAD"])  # LAD plays, but Ohtani isn't probable today
    plan = optimize_lineup([_ohtani(slot="UTIL")], {"UTIL": 1, "P": 1, "BE": 1},
                           schedule, is_points=True)
    assert plan.assignments[1] == "UTIL"
    assert plan.two_way_pitching == []
    assert plan.two_way_prompt() is None
    assert plan.moves == []                   # already at UTIL, no churn


def test_ohtani_stays_a_hitter_when_no_pitching_slot_free():
    """With every pitching slot taken by a locked starter, he can't pitch -- so he hits."""
    now = dt.datetime(2026, 6, 20, 20, 0, tzinfo=dt.timezone.utc)
    schedule = make_schedule(playing=["LAD", "NYY"], probables={"LAD": "Shohei Ohtani"})
    schedule.game_starts[ESPN_TO_MLB_ID["NYY"]] = dt.datetime(2026, 6, 20, 19, 0, tzinfo=dt.timezone.utc)
    roster = [
        _ohtani(slot="UTIL"),
        pitcher(3, "Locked Arm", team="NYY", slots=("SP", "P"), pts=20, slot="P"),  # game started
    ]
    plan = optimize_lineup(roster, {"UTIL": 1, "P": 1, "BE": 2}, schedule, is_points=True, now=now)
    assert plan.assignments[3] == "P"         # locked pitcher holds the only P slot
    assert plan.assignments[1] == "UTIL"      # Ohtani falls back to hitting
    assert plan.two_way_pitching == []


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
