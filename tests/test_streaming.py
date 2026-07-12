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
    assert recs[0].slot_gain > 0


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


def test_keeper_is_protected_recent_add_is_dropped():
    """The Nick Martinez bug: a long-held starter is the weakest arm by skill, but the
    streamer-drop must recycle a recently-added arm, not churn the established keeper."""
    import datetime as dt
    day = _one_game_day()
    offense = {136: 0.620, 147: 0.760}
    today = dt.date.fromisoformat("2026-06-21")
    keeper = pitcher(1, "Established Starter", team="Atl", slots=("SP", "P"),
                     stats={"ERA": 5.2, "WHIP": 1.45, "K": 120, "OUTS": 450},  # weakest skill
                     acquired=today - dt.timedelta(days=49), acq_type="ADD")
    streamer = pitcher(2, "Recent Pickup", team="Bos", slots=("SP", "P"),
                       stats={"ERA": 3.6, "WHIP": 1.22, "K": 150, "OUTS": 470},
                       acquired=today - dt.timedelta(days=2), acq_type="ADD")
    roster = [keeper, streamer]
    free_agents = [pitcher(100, "Stream Ace", team="NYY", slots=("SP", "P"),
                           stats={"ERA": 3.0, "WHIP": 1.05, "K": 200, "OUTS": 540})]

    recs = streaming.recommend_streamers(roster, free_agents, [day], offense)
    assert len(recs) == 1
    assert recs[0].drop.player_id == 2          # recent pickup, not the established keeper
    assert recs[0].drop_is_streamer is True     # recognized as recycling the streamer slot


def test_drafted_pitcher_is_never_a_streamer_drop():
    import datetime as dt
    day = _one_game_day()
    offense = {136: 0.620, 147: 0.760}
    today = dt.date.fromisoformat("2026-06-21")
    drafted = pitcher(1, "Drafted Arm", team="Atl", slots=("SP", "P"),
                      stats={"ERA": 5.5, "WHIP": 1.50, "K": 100, "OUTS": 440},  # weakest
                      acquired=today - dt.timedelta(days=2), acq_type="DRAFT")  # but DRAFTED
    free_agents = [pitcher(100, "Stream Ace", team="NYY", slots=("SP", "P"),
                           stats={"ERA": 3.0, "WHIP": 1.05, "K": 200, "OUTS": 540})]

    recs = streaming.recommend_streamers([drafted], free_agents, [day], offense)
    # The available arm is still shown (landscape), but with no disposable arm to drop it is
    # not an executable upgrade -- so the drafted keeper is never proposed as a churn.
    assert len(recs) == 1
    assert recs[0].drop is None
    assert recs[0].is_upgrade is False
    assert recs[0].staff_gain is not None       # staff-value metric still reported (no drop needed)


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


def test_start_label_relative_then_absolute():
    assert streaming._start_label("2026-07-05", "2026-07-05") == "Today"
    assert streaming._start_label("2026-07-06", "2026-07-05") == "Tomorrow"
    far = streaming._start_label("2026-07-08", "2026-07-05")
    assert "Jul 8" in far and "Today" not in far and "Tomorrow" not in far
    assert streaming._start_label("2026-07-08", None).endswith("Jul 8")  # absolute w/o a ref date
    assert streaming._start_label("", "2026-07-05") == "TBD"             # unparseable -> TBD


def test_days_out_counts_whole_days():
    assert streaming._days_out("2026-07-08", "2026-07-05") == 3
    assert streaming._days_out("2026-07-05", "2026-07-05") == 0
    assert streaming._days_out("2026-07-05", None) is None


def test_summary_omits_raw_iso_date():
    """The start date is surfaced as a highlighted label, not buried in the summary."""
    day = _one_game_day()
    offense = {136: 0.620, 147: 0.760}
    ace = pitcher(100, "Stream Ace", team="NYY", slots=("SP", "P"),
                  stats={"ERA": 3.4, "WHIP": 1.15, "K": 180, "OUTS": 510})
    ev = streaming.evaluate(ace, day, offense, LG_OPS, today_date=day.date)
    assert "2026-" not in ev.summary
    assert ev.start_label == "Today" and ev.days_out == 0


def _yanks_day(date: str, ace: bool = False) -> DaySchedule:
    """NYY (147) home vs Mariners (136) on `date`; the ace is probable only when `ace`."""
    return DaySchedule(
        date=date, playing_team_ids={147, 136},
        probable_pitchers={147: "Stream Ace"} if ace else {},
        opponents={147: 136, 136: 147}, home_teams={147},
        team_names={147: "Yankees", 136: "Mariners"},
    )


def test_recommend_highlights_start_date_across_rolling_window():
    """A start several days out is surfaced with its absolute label and correct days_out."""
    offense = {136: 0.620, 147: 0.760}
    ace = pitcher(100, "Stream Ace", team="NYY", slots=("SP", "P"),
                  stats={"ERA": 3.0, "WHIP": 1.05, "K": 200, "OUTS": 540})
    droppable = pitcher(1, "Weak SP", team="Atl", slots=("SP", "P"),
                        stats={"ERA": 5.5, "WHIP": 1.55, "K": 70, "OUTS": 430})
    schedules = [_yanks_day("2026-07-05"), _yanks_day("2026-07-06"),
                 _yanks_day("2026-07-07", ace=True)]          # probable only on day 3

    recs = streaming.recommend_streamers([droppable], [ace], schedules, offense)

    assert len(recs) == 1
    ev = recs[0].evaluation
    assert ev.start_day == "2026-07-07"
    assert ev.days_out == 2
    assert "Jul 7" in ev.start_label                          # absolute label for a plan-ahead start


def test_recommend_marks_today_start():
    day = _one_game_day()                                     # ace probable this same day
    offense = {136: 0.620, 147: 0.760}
    roster = [pitcher(1, "Droppable", team="Atl", slots=("SP", "P"),
                      stats={"ERA": 5.0, "WHIP": 1.5, "K": 80, "OUTS": 450})]
    fas = [pitcher(100, "Stream Ace", team="NYY", slots=("SP", "P"),
                   stats={"ERA": 3.2, "WHIP": 1.10, "K": 190, "OUTS": 520})]

    recs = streaming.recommend_streamers(roster, fas, [day], offense)

    assert recs[0].evaluation.start_label == "Today"
    assert recs[0].evaluation.days_out == 0


def test_recommend_empty_schedule_returns_nothing():
    assert streaming.recommend_streamers([], [], [], {}) == []


def test_landscape_shows_non_upgrades_not_just_upgrades():
    """A fringe available starter is surfaced for scouting even when it can't beat the arm
    you'd drop -- flagged is_upgrade=False so it is never proposed as a move."""
    day = _one_game_day(ace_name="Fringe Starter")  # NYY probable is the fringe FA
    offense = {136: 0.620, 147: 0.760}
    strong = pitcher(1, "Strong Keeper Arm", team="Atl", slots=("SP", "P"),
                     stats={"ERA": 2.8, "WHIP": 1.00, "K": 220, "OUTS": 560})   # droppable, strong
    fringe = pitcher(100, "Fringe Starter", team="NYY", slots=("SP", "P"),
                     stats={"ERA": 4.9, "WHIP": 1.48, "K": 105, "OUTS": 470})

    recs = streaming.recommend_streamers([strong], [fringe], [day], offense)

    assert len(recs) == 1                         # shown despite not being an upgrade
    assert recs[0].slot_gain < 0
    assert recs[0].is_upgrade is False


def test_reports_both_slot_and_staff_gains():
    """Each option carries two gains: vs the arm you'd drop (slot) and vs your rotation's
    median skill (staff)."""
    day = _one_game_day()                         # NYY home vs Mariners (0.620 OPS)
    offense = {136: 0.620, 147: 0.760}
    weak1 = pitcher(1, "Weak One", team="Atl", slots=("SP", "P"),
                    stats={"ERA": 5.4, "WHIP": 1.52, "K": 90, "OUTS": 440})
    weak2 = pitcher(2, "Weak Two", team="Mia", slots=("SP", "P"),
                    stats={"ERA": 5.0, "WHIP": 1.45, "K": 100, "OUTS": 450})
    ace = pitcher(100, "Stream Ace", team="NYY", slots=("SP", "P"),
                  stats={"ERA": 3.0, "WHIP": 1.05, "K": 200, "OUTS": 540})

    recs = streaming.recommend_streamers([weak1, weak2], [ace], [day], offense)

    assert recs[0].slot_gain > 0                   # beats the specific arm it would drop
    assert recs[0].staff_gain is not None
    assert recs[0].staff_gain > 0                  # and clears the weak rotation's median skill


def test_landscape_shows_options_beyond_droppable_count():
    """More available starts than disposable arms: the extras still appear (drop=None),
    ranked in, as scouting context rather than executable moves."""
    offense = {147: 0.760, 136: 0.620, 111: 0.700, 110: 0.720}
    two_probables = DaySchedule(
        date="2026-07-05", playing_team_ids={147, 136, 111, 110},
        probable_pitchers={147: "Ace One", 111: "Ace Two"},
        opponents={147: 136, 136: 147, 111: 110, 110: 111},
        home_teams={147, 111},
        team_names={147: "Yankees", 136: "Mariners", 111: "Red Sox", 110: "Orioles"},
    )
    ace1 = pitcher(100, "Ace One", team="NYY", slots=("SP", "P"),
                   stats={"ERA": 3.0, "WHIP": 1.05, "K": 205, "OUTS": 540})
    ace2 = pitcher(101, "Ace Two", team="Bos", slots=("SP", "P"),
                   stats={"ERA": 3.1, "WHIP": 1.08, "K": 195, "OUTS": 530})
    weak = pitcher(1, "Weak SP", team="Atl", slots=("SP", "P"),
                   stats={"ERA": 5.6, "WHIP": 1.55, "K": 70, "OUTS": 430})   # only droppable arm

    recs = streaming.recommend_streamers([weak], [ace1, ace2], [two_probables], offense)

    assert len(recs) == 2                         # both available starts are surfaced
    assert recs[0].drop is not None               # the top option gets the lone disposable arm
    assert recs[1].drop is None                   # the second has no distinct drop...
    assert recs[1].is_upgrade is False            # ...so it is scouting-only, never queued
