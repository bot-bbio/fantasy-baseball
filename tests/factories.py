"""Tiny builders for test players and schedules (no network, no espn-api)."""
from __future__ import annotations

from data.mlb_schedule import ESPN_TO_MLB_ID, DaySchedule
from models import RosterPlayer


def make_schedule(date="2026-06-20", playing=(), probables=None) -> DaySchedule:
    """Build a DaySchedule from ESPN team abbreviations."""
    ids = {ESPN_TO_MLB_ID[t] for t in playing}
    probs = {ESPN_TO_MLB_ID[t]: name for t, name in (probables or {}).items()}
    return DaySchedule(date=date, playing_team_ids=ids, probable_pitchers=probs)


def hitter(
    pid, name, team="NYY", slots=("UTIL",), pts=10.0, slot="BE",
    status="ACTIVE", injured=False, owned=50.0, stats=None, season=None, position="OF",
) -> RosterPlayer:
    return RosterPlayer(
        player_id=pid, name=name, pro_team=team, position=position,
        eligible_slots=list(slots), lineup_slot=slot, injury_status=status,
        injured=injured, projected_points=pts, projected_stats=stats or {},
        season_stats=season or {}, percent_owned=owned,
    )


def pitcher(
    pid, name, team="NYY", slots=("SP", "P"), pts=20.0, slot="BE",
    status="ACTIVE", injured=False, owned=50.0, stats=None, season=None, position="SP",
) -> RosterPlayer:
    return RosterPlayer(
        player_id=pid, name=name, pro_team=team, position=position,
        eligible_slots=list(slots), lineup_slot=slot, injury_status=status,
        injured=injured, projected_points=pts, projected_stats=stats or {},
        season_stats=season or {}, percent_owned=owned,
    )
