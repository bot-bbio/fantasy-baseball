"""Read-only ESPN access via the espn-api library.

Wraps ``espn_api.baseball.League`` and maps its Player objects into our
``RosterPlayer`` model. Everything here is GET-only; writes go through
``browser/espn_ui.py``.
"""
from __future__ import annotations

from functools import lru_cache

from espn_api.baseball import League
from espn_api.baseball.constant import POSITION_MAP, STATS_MAP

import config
from analysis.budget import AcquisitionBudget, compute_budget
from models import RosterPlayer


def _to_roster_player(player) -> RosterPlayer:
    """Map an espn-api baseball Player into our RosterPlayer."""
    season = player.stats.get(0, {})
    projected_stats = {
        str(k): float(v)
        for k, v in season.get("projected_breakdown", {}).items()
        if isinstance(v, (int, float))
    }
    season_stats = {
        str(k): float(v)
        for k, v in season.get("breakdown", {}).items()
        if isinstance(v, (int, float))
    }
    return RosterPlayer(
        player_id=int(player.playerId),
        name=player.name,
        pro_team=str(player.proTeam),
        position=str(player.position),
        eligible_slots=list(player.eligibleSlots),
        lineup_slot=player.lineupSlot or "",
        injury_status=player.injuryStatus or "ACTIVE",
        injured=bool(getattr(player, "injured", False)),
        projected_points=float(player.projected_total_points or 0.0),
        projected_stats=projected_stats,
        season_stats=season_stats,
        percent_owned=float(getattr(player, "percent_owned", 0) or 0),
    )


class LeagueReader:
    """Lazily-connected read facade over a single ESPN baseball league."""

    def __init__(self, settings: config.Settings | None = None):
        self.settings = settings or config.get_settings()
        self._league: League | None = None

    @property
    def league(self) -> League:
        if self._league is None:
            self._league = League(
                league_id=self.settings.league_id,
                year=self.settings.year,
                espn_s2=self.settings.espn_s2,
                swid=self.settings.swid,
            )
        return self._league

    @property
    def scoring_period(self) -> int:
        """Current scoring period id (ESPN's notion of 'today')."""
        return self.league.scoringPeriodId

    def scoring_format(self) -> str:
        """e.g. 'H2H_POINTS', 'H2H_CATEGORY', 'ROTO'."""
        return self.league.settings.scoring_type or "H2H_POINTS"

    def is_points_league(self) -> bool:
        return "POINT" in self.scoring_format().upper()

    @lru_cache(maxsize=1)
    def scored_categories(self) -> tuple[str, ...]:
        """Stat abbreviations the league actually scores (for category ranking)."""
        raw = getattr(self.league.settings, "_raw_scoring_settings", {}) or {}
        cats = []
        for item in raw.get("scoringItems", []):
            stat_id = item.get("statId")
            if stat_id is None:
                continue
            cats.append(STATS_MAP.get(int(stat_id), str(stat_id)))
        return tuple(cats)

    def my_team(self):
        team = self.league.get_team_data(self.settings.team_id)
        if team is None:
            raise ValueError(
                f"Team id {self.settings.team_id} not found in league "
                f"{self.settings.league_id}. Check ESPN_TEAM_ID in .env."
            )
        return team

    def roster(self) -> list[RosterPlayer]:
        return [_to_roster_player(p) for p in self.my_team().roster]

    def free_agents(self, position: str | None = None, size: int = 75) -> list[RosterPlayer]:
        players = self.league.free_agents(size=size, position=position)
        return [_to_roster_player(p) for p in players]

    def lineup_slot_counts(self) -> dict[str, int]:
        """Active-roster shape: slot name -> number of slots (incl. BE/IL)."""
        data = self.league.espn_request.league_get(params={"view": "mSettings"})
        counts = data["settings"]["rosterSettings"]["lineupSlotCounts"]
        result: dict[str, int] = {}
        for slot_id, count in counts.items():
            if not count:
                continue
            name = POSITION_MAP.get(int(slot_id), str(slot_id))
            result[name] = int(count)
        return result

    def acquisition_budget(self) -> AcquisitionBudget:
        """How many add/drops remain right now (league caps minus my usage).

        One request pulls the league's acquisition settings and my team's transaction
        counter; :func:`analysis.budget.compute_budget` turns them into a remaining count.
        """
        data = self.league.espn_request.league_get(params={"view": ["mSettings", "mTeam"]})
        acq = data.get("settings", {}).get("acquisitionSettings", {}) or {}
        period = data.get("status", {}).get("currentMatchupPeriod", 0)
        counter: dict = {}
        for team in data.get("teams", []):
            if team.get("id") == self.settings.team_id:
                counter = team.get("transactionCounter", {}) or {}
                break
        return compute_budget(acq, counter, period)

    def standings(self):
        return self.league.standings()

    def current_box_score(self):
        """The box score for the current matchup that includes my team (or None)."""
        my_id = self.settings.team_id
        for box in self.league.box_scores():
            home = getattr(box.home_team, "team_id", None)
            away = getattr(box.away_team, "team_id", None)
            if my_id in (home, away):
                return box
        return None
