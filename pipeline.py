"""Orchestration shared by the CLI and the scheduled job.

Pulls the pieces together (reader + schedule + analysis) so both entry points build
lineup plans and waiver recommendations the same way.
"""
from __future__ import annotations

import datetime as dt

import config
from analysis import streaming, waivers
from analysis.lineup import LineupPlan, optimize_lineup
from data import mlb_offense, mlb_schedule
from data.mlb_schedule import DaySchedule
from espn_client.reader import LeagueReader
from models import RosterPlayer
from research import research as research_mod
from streamer_state import StreamerLog


def _team_offense(year: int) -> dict[int, float]:
    """Team OPS for the streaming model; empty on failure (model falls back to neutral)."""
    try:
        return mlb_offense.team_offense_ops(year)
    except Exception:
        return {}


def _research(year: int):
    """FanGraphs/platoon research bundle; None on failure (model falls back to ESPN)."""
    try:
        return research_mod.build(year)
    except Exception:
        return None


def _streamer_log(roster: list[RosterPlayer]) -> StreamerLog:
    """Load the streamer-slot log and self-heal it against the live roster.

    Pruning entries for pitchers no longer rostered means a streamer you dropped (even
    manually on ESPN) stops being tracked, so the log always reflects real slots.
    """
    try:
        log = StreamerLog.load()
        if log.sync(roster):
            log.save()
        return log
    except Exception:
        return StreamerLog(path=config.STREAMERS_FILE, entries=[])


def upcoming_schedules(timezone: str, days: int = 1) -> list[DaySchedule]:
    """Fetch today's (and optionally the next days') MLB schedules."""
    start = config.local_today(timezone)
    return [mlb_schedule.fetch_day(start + dt.timedelta(days=offset)) for offset in range(days)]


def build_lineup_plan(
    reader: LeagueReader, schedule: DaySchedule
) -> tuple[LineupPlan, list[RosterPlayer]]:
    roster = reader.roster()
    plan = optimize_lineup(
        roster,
        reader.lineup_slot_counts(),
        schedule,
        is_points=reader.is_points_league(),
        categories=reader.scored_categories(),
    )
    return plan, roster


def gather_waiver_recs(
    reader: LeagueReader, schedules: list[DaySchedule], *, size: int = 75
):
    roster = reader.roster()
    free_agents = reader.free_agents(size=size)
    pitchers = reader.free_agents(position="SP", size=40) or free_agents
    offense = _team_offense(reader.settings.year)
    research = _research(reader.settings.year)
    categories = reader.scored_categories()
    streamer_ids = frozenset(_streamer_log(roster).ids())

    streams = streaming.recommend_streamers(
        roster, pitchers, schedules, offense,
        research=research, scored_categories=categories,
        streamer_ids=streamer_ids,
    )
    hitters = waivers.find_best_available_hitters(
        roster, free_agents,
        is_points=reader.is_points_league(),
        categories=categories,
    )
    return streams, hitters
