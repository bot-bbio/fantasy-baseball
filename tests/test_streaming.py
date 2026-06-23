"""Tests for the streaming-pitcher model."""
from __future__ import annotations

from analysis import streaming
from data.mlb_offense import parse_team_ops
from data.mlb_schedule import DaySchedule
from data.park_factors import park_factor
from tests.factories import pitcher

LG_OPS = 0.715


def test_matchup_score_rewards_weak_offense():
    weak = streaming._matchup_score(0.620, LG_OPS)
    strong = streaming._matchup_score(0.800, LG_OPS)
    average = streaming._matchup_score(LG_OPS, LG_OPS)
    assert weak > average > strong
    assert abs(average - 50.0) < 1e-6


def test_park_score_rewards_pitcher_parks():
    assert streaming._park_score(95) > streaming._park_score(100) > streaming._park_score(112)


def test_skill_score_rewards_better_stats():
    ace = streaming._skill_score({"ERA": 2.8, "WHIP": 1.05, "K": 200, "OUTS": 540})
    scrub = streaming._skill_score({"ERA": 5.4, "WHIP": 1.55, "K": 90, "OUTS": 480})
    assert ace > scrub


def _one_game_day(streamer_team_mlb=147, opp_mlb=136, opp_ops=0.620, ace_name="Stream Ace"):
    """A single-game day: streamer's team at home vs `opp`."""
    return DaySchedule(
        date="2026-06-21",
        playing_team_ids={streamer_team_mlb, opp_mlb},
        probable_pitchers={streamer_team_mlb: ace_name},
        opponents={streamer_team_mlb: opp_mlb, opp_mlb: streamer_team_mlb},
        home_teams={streamer_team_mlb},
        venue_names={streamer_team_mlb: "Yankee Stadium", opp_mlb: "Yankee Stadium"},
        team_names={streamer_team_mlb: "Yankees", opp_mlb: "Mariners"},
    )


def test_evaluate_produces_score_and_summary():
    day = _one_game_day()
    offense = {136: 0.620, 147: 0.760}
    ace = pitcher(100, "Stream Ace", team="NYY", slots=("SP", "P"),
                  stats={"ERA": 3.4, "WHIP": 1.15, "K": 180, "OUTS": 510},
                  season={"ERA": 3.0, "WHIP": 1.10, "K": 110, "OUTS": 300})
    ev = streaming.evaluate(ace, day, offense, LG_OPS)
    assert 0 <= ev.score <= 100
    assert ev.score > 55                      # good arm, weak opp -> above average
    assert "Mariners" in ev.summary
    assert ev.opponent_ops == 0.620


def test_recommend_streamers_ranks_and_pairs_drop():
    day = _one_game_day()
    offense = {136: 0.620, 147: 0.760}
    roster = [pitcher(1, "Droppable", team="Atl", slots=("SP", "P"),
                      stats={"ERA": 5.0, "WHIP": 1.5, "K": 80, "OUTS": 450})]
    free_agents = [
        pitcher(100, "Stream Ace", team="NYY", slots=("SP", "P"),
                stats={"ERA": 3.2, "WHIP": 1.10, "K": 190, "OUTS": 520}),
        pitcher(101, "Not Pitching", team="Bos", slots=("SP", "P"),
                stats={"ERA": 2.5, "WHIP": 1.0, "K": 200, "OUTS": 540}),  # no start this day
    ]
    recs = streaming.recommend_streamers(roster, free_agents, [day], offense)
    assert len(recs) == 1
    assert recs[0].evaluation.player.player_id == 100   # only one with a probable start
    assert recs[0].drop.player_id == 1
    assert recs[0].value_gain > 0


def test_recommend_protects_core_arm_via_streamer_slot():
    """A slumping core ace can be the weakest arm by skill; tracking the streamer slot
    must recycle the streamer instead of dropping that ace."""
    day = _one_game_day()                       # NYY home vs Mariners (0.620 OPS)
    offense = {136: 0.620, 147: 0.760}
    core = pitcher(1, "Core Ace", team="Atl", slots=("SP", "P"),
                   stats={"ERA": 5.2, "WHIP": 1.45, "K": 120, "OUTS": 450})   # weakest skill
    old_streamer = pitcher(2, "Old Streamer", team="Bos", slots=("SP", "P"),
                           stats={"ERA": 3.5, "WHIP": 1.20, "K": 160, "OUTS": 480})
    roster = [core, old_streamer]
    free_agents = [pitcher(100, "Stream Ace", team="NYY", slots=("SP", "P"),
                           stats={"ERA": 3.0, "WHIP": 1.05, "K": 200, "OUTS": 540})]

    # Untracked: the weakest arm (the slumping core ace) gets paired as the drop.
    plain = streaming.recommend_streamers(roster, free_agents, [day], offense)
    assert plain[0].drop.player_id == 1
    assert plain[0].drop_is_streamer is False

    # Tracked: the old streamer slot is recycled; the core ace is protected.
    tracked = streaming.recommend_streamers(
        roster, free_agents, [day], offense, streamer_ids=frozenset({2})
    )
    assert tracked[0].drop.player_id == 2
    assert tracked[0].drop_is_streamer is True


def test_reliever_protected_by_bullpen_floor():
    """A reliever can be the weakest non-starting arm by skill, but with only the floor
    number of relievers on the roster, none may be proposed as a drop."""
    day = _one_game_day()                       # NYY home vs Mariners (0.620 OPS)
    offense = {136: 0.620, 147: 0.760}
    # Two relievers (no SP eligibility) -- exactly the floor -- plus a weak starter.
    rp1 = pitcher(1, "Closer", team="Atl", slots=("RP", "P"), position="RP",
                  stats={"ERA": 4.8, "WHIP": 1.40, "K": 60, "OUTS": 180})
    rp2 = pitcher(2, "Setup Man", team="Bos", slots=("RP", "P"), position="RP",
                  stats={"ERA": 5.5, "WHIP": 1.55, "K": 50, "OUTS": 170})  # weakest skill
    starter = pitcher(3, "Weak Starter", team="Atl", slots=("SP", "P"),
                      stats={"ERA": 5.0, "WHIP": 1.50, "K": 80, "OUTS": 450})
    roster = [rp1, rp2, starter]
    free_agents = [pitcher(100, "Stream Ace", team="NYY", slots=("SP", "P"),
                           stats={"ERA": 3.0, "WHIP": 1.05, "K": 200, "OUTS": 540})]

    recs = streaming.recommend_streamers(roster, free_agents, [day], offense)
    assert len(recs) == 1
    # The starter is dropped even though a reliever scores worse on raw skill.
    assert recs[0].drop.player_id == 3


def test_reliever_droppable_when_surplus_above_floor():
    """A third reliever is surplus over the floor, so the weakest one may be dropped."""
    day = _one_game_day()
    offense = {136: 0.620, 147: 0.760}
    rp_weak = pitcher(2, "Weak Reliever", team="Bos", slots=("RP", "P"), position="RP",
                      stats={"ERA": 6.0, "WHIP": 1.70, "K": 40, "OUTS": 150})  # weakest
    rp_mid = pitcher(1, "Closer", team="Atl", slots=("RP", "P"), position="RP",
                     stats={"ERA": 3.2, "WHIP": 1.10, "K": 90, "OUTS": 200})
    rp_good = pitcher(3, "Setup Man", team="Atl", slots=("RP", "P"), position="RP",
                      stats={"ERA": 2.8, "WHIP": 1.00, "K": 95, "OUTS": 210})
    roster = [rp_weak, rp_mid, rp_good]         # three relievers, floor is two
    free_agents = [pitcher(100, "Stream Ace", team="NYY", slots=("SP", "P"),
                           stats={"ERA": 3.0, "WHIP": 1.05, "K": 200, "OUTS": 540})]

    recs = streaming.recommend_streamers(roster, free_agents, [day], offense)
    assert len(recs) == 1
    assert recs[0].drop.player_id == 2          # only the weakest surplus reliever


def test_parse_team_ops_handles_payload():
    payload = {"stats": [{"splits": [
        {"team": {"id": 147}, "stat": {"ops": ".780"}},
        {"team": {"id": 136}, "stat": {"ops": ".640"}},
    ]}]}
    ops = parse_team_ops(payload)
    assert ops == {147: 0.780, 136: 0.640}


def test_park_factor_defaults_neutral():
    assert park_factor(137) == 95     # Oracle Park (pitcher)
    assert park_factor(999999) == 100  # unknown -> neutral


def test_two_start_bonus_raises_score():
    day = _one_game_day()
    offense = {136: 0.620, 147: 0.760}
    ace = pitcher(100, "Stream Ace", team="NYY", slots=("SP", "P"),
                  stats={"ERA": 3.4, "WHIP": 1.15, "K": 180, "OUTS": 510})
    one = streaming.evaluate(ace, day, offense, LG_OPS, two_start=False)
    two = streaming.evaluate(ace, day, offense, LG_OPS, two_start=True)
    assert two.score > one.score
    assert two.two_start is True


def test_k_weight_reflects_categories():
    assert streaming._k_weight(("K",)) > streaming._k_weight(()) > streaming._k_weight(("ERA", "WHIP"))


def test_skill_score_uses_advanced_metrics():
    good = streaming._skill_score({"SIERA": 3.0, "KBB": 0.20, "WHIP": 1.05})
    bad = streaming._skill_score({"SIERA": 4.6, "KBB": 0.07, "WHIP": 1.40})
    assert good > bad
