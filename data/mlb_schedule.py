"""Today's MLB schedule + probable pitchers, from the free MLB Stats API.

We deliberately source "who plays today" and "who is the probable starter" from
statsapi.mlb.com rather than ESPN: it's an official, no-auth, stable endpoint, which
keeps the most schedule-sensitive logic off ESPN's fragile surface.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

import requests


def _parse_iso_utc(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    try:
        return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None

SCHEDULE_URL = "https://statsapi.mlb.com/api/v1/schedule"

# ESPN proTeam abbreviation -> MLB Stats API team id (ids are permanent/stable).
ESPN_TO_MLB_ID = {
    "Bal": 110, "Bos": 111, "LAA": 108, "ChW": 145, "Cle": 114, "Det": 116,
    "KC": 118, "Mil": 158, "Min": 142, "NYY": 147, "Oak": 133, "Sea": 136,
    "Tex": 140, "Tor": 141, "Atl": 144, "ChC": 112, "Cin": 113, "Hou": 117,
    "LAD": 119, "Wsh": 120, "NYM": 121, "Phi": 143, "Pit": 134, "StL": 138,
    "SD": 135, "SF": 137, "Col": 115, "Mia": 146, "Ari": 109, "TB": 139,
}


@dataclass
class DaySchedule:
    """Which MLB teams play on a date, their probable SPs, start times, opponents, venues."""

    date: str
    playing_team_ids: set[int] = field(default_factory=set)
    probable_pitchers: dict[int, str] = field(default_factory=dict)  # mlb_team_id -> pitcher name
    game_starts: dict[int, dt.datetime] = field(default_factory=dict)  # mlb_team_id -> first pitch (UTC)
    opponents: dict[int, int] = field(default_factory=dict)           # mlb_team_id -> opponent id
    home_teams: set[int] = field(default_factory=set)                 # teams playing at home
    venue_names: dict[int, str] = field(default_factory=dict)         # mlb_team_id -> venue name
    team_names: dict[int, str] = field(default_factory=dict)          # mlb_team_id -> team name
    probable_pitcher_ids: dict[int, int] = field(default_factory=dict)  # mlb_team_id -> pitcher mlbam id

    def team_plays(self, espn_abbrev: str) -> bool:
        team_id = ESPN_TO_MLB_ID.get(espn_abbrev)
        return team_id is not None and team_id in self.playing_team_ids

    def probable_pitcher(self, espn_abbrev: str) -> str | None:
        team_id = ESPN_TO_MLB_ID.get(espn_abbrev)
        if team_id is None:
            return None
        return self.probable_pitchers.get(team_id)

    def has_started(self, espn_abbrev: str, now: dt.datetime) -> bool:
        """True if the player's team game has already begun (ESPN locks such players)."""
        team_id = ESPN_TO_MLB_ID.get(espn_abbrev)
        start = self.game_starts.get(team_id) if team_id is not None else None
        return start is not None and now >= start

    def opponent_id(self, espn_abbrev: str) -> int | None:
        """MLB team id of the opponent the player's team faces on this date."""
        team_id = ESPN_TO_MLB_ID.get(espn_abbrev)
        return self.opponents.get(team_id) if team_id is not None else None

    def home_team_id(self, espn_abbrev: str) -> int | None:
        """The home team's MLB id for the player's game (whose park is used)."""
        team_id = ESPN_TO_MLB_ID.get(espn_abbrev)
        if team_id is None:
            return None
        if team_id in self.home_teams:
            return team_id
        return self.opponents.get(team_id)

    def venue_name(self, espn_abbrev: str) -> str | None:
        team_id = ESPN_TO_MLB_ID.get(espn_abbrev)
        return self.venue_names.get(team_id) if team_id is not None else None

    def probable_pitcher_id(self, espn_abbrev: str) -> int | None:
        team_id = ESPN_TO_MLB_ID.get(espn_abbrev)
        return self.probable_pitcher_ids.get(team_id) if team_id is not None else None

    def team_name(self, mlb_team_id: int | None) -> str | None:
        return self.team_names.get(mlb_team_id) if mlb_team_id is not None else None


def fetch_day(date: dt.date | None = None, *, timeout: int = 15) -> DaySchedule:
    """Fetch the schedule for a single date (defaults to today, local)."""
    date = date or dt.date.today()
    params = {"sportId": 1, "date": date.isoformat(), "hydrate": "probablePitcher,venue"}
    response = requests.get(SCHEDULE_URL, params=params, timeout=timeout)
    response.raise_for_status()
    return parse_schedule(response.json(), date.isoformat())


def parse_schedule(data: dict, date: str) -> DaySchedule:
    """Pure parser over a MLB Stats API schedule payload (kept separate for testing)."""
    schedule = DaySchedule(date=date)
    for day in data.get("dates", []):
        for game in day.get("games", []):
            # Skip games that won't be played (postponed, cancelled, suspended).
            status = game.get("status", {}).get("detailedState", "")
            if status in {"Postponed", "Cancelled", "Canceled", "Suspended"}:
                continue
            start = _parse_iso_utc(game.get("gameDate"))
            venue_name = game.get("venue", {}).get("name")
            sides = {
                side: game.get("teams", {}).get(side, {}).get("team", {})
                for side in ("home", "away")
            }
            ids = {side: team.get("id") for side, team in sides.items()}
            for side, team in sides.items():
                team_id = ids[side]
                if team_id is None:
                    continue
                schedule.playing_team_ids.add(team_id)
                if team.get("name"):
                    schedule.team_names[team_id] = team["name"]
                probable = game["teams"][side].get("probablePitcher")
                if probable and probable.get("fullName"):
                    schedule.probable_pitchers[team_id] = probable["fullName"]
                    if probable.get("id"):
                        schedule.probable_pitcher_ids[team_id] = probable["id"]
                if start is not None:
                    # Keep the earliest game start for teams with a doubleheader.
                    existing = schedule.game_starts.get(team_id)
                    if existing is None or start < existing:
                        schedule.game_starts[team_id] = start
                opponent = ids["away"] if side == "home" else ids["home"]
                if opponent is not None:
                    schedule.opponents[team_id] = opponent
                if venue_name:
                    schedule.venue_names[team_id] = venue_name
                if side == "home":
                    schedule.home_teams.add(team_id)
    return schedule
