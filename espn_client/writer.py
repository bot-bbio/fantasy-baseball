"""Write layer: set lineup / add-drop via ESPN's authenticated transactions API.

ESPN has no official write API, but the same espn_s2/SWID cookies that authenticate the
read API also authenticate the write host (lm-api-writes.fantasy.espn.com). A lineup
change is a single POST: a ROSTER transaction whose items each move one player from one
lineupSlotId to another.

Guardrails: dry-run is the default (builds and returns the payload, sends nothing). The
caller verifies a real write by re-reading the roster through the API.
"""
from __future__ import annotations

from dataclasses import dataclass

import requests
from espn_api.baseball.constant import POSITION_MAP

import config
from analysis.lineup import LineupPlan

WRITE_URL = (
    "https://lm-api-writes.fantasy.espn.com/apis/v3/games/flb/seasons/{year}"
    "/segments/0/leagues/{league_id}/transactions/"
)
_HEADERS = {
    "Content-Type": "application/json",
    "x-fantasy-platform": "kona",
    "x-fantasy-source": "kona",
}


class WriteError(RuntimeError):
    """Raised when a write cannot be built or is rejected by ESPN."""


@dataclass
class WriteResult:
    submitted: int = 0
    status_code: int | None = None
    ok: bool = False
    message: str = ""


def _slot_id(slot_name: str) -> int:
    """Map a lineup slot name (e.g. 'OF', 'P', 'BE') to ESPN's lineupSlotId."""
    slot_id = POSITION_MAP.get(slot_name)
    if not isinstance(slot_id, int):
        raise WriteError(f"Unknown lineup slot {slot_name!r}; cannot build write.")
    return slot_id


def build_add_drop_payload(
    add_id: int, drop_id: int, team_id: int, scoring_period: int, swid: str
) -> dict:
    """Build a FREEAGENT transaction body that adds one player and drops another.

    Same authenticated write host as the lineup change. A free-agent pickup paired with a
    drop is a single transaction: an ADD item (from the FA pool, team 0, to our team) and a
    DROP item (from our team to the pool). ``bidAmount`` is 0 for a straight free-agent add.
    """
    items = [
        {"playerId": int(add_id), "type": "ADD", "fromTeamId": 0, "toTeamId": team_id},
        {"playerId": int(drop_id), "type": "DROP", "fromTeamId": team_id, "toTeamId": 0},
    ]
    return {
        "isLeagueManager": False,
        "teamId": team_id,
        "type": "FREEAGENT",
        "memberId": swid,
        "scoringPeriodId": scoring_period,
        "executionType": "EXECUTE",
        "bidAmount": 0,
        "items": items,
    }


def build_lineup_payload(
    plan: LineupPlan, team_id: int, scoring_period: int, swid: str
) -> dict:
    """Build the ROSTER transaction body for a set of lineup moves."""
    items = [
        {
            "playerId": move.player_id,
            "type": "LINEUP",
            "fromLineupSlotId": _slot_id(move.from_slot),
            "toLineupSlotId": _slot_id(move.to_slot),
        }
        for move in plan.moves
    ]
    return {
        "isLeagueManager": False,
        "teamId": team_id,
        "type": "ROSTER",
        "memberId": swid,
        "scoringPeriodId": scoring_period,
        "executionType": "EXECUTE",
        "items": items,
    }


class LineupWriter:
    """Submits lineup changes to ESPN for one team."""

    def __init__(self, settings: config.Settings | None = None):
        self.settings = settings or config.get_settings(require_cookies=True)
        if not self.settings.has_cookies:
            raise WriteError("No ESPN cookies; run `python setup_cookies.py` first.")

    def set_lineup(
        self, plan: LineupPlan, scoring_period: int, *, dry_run: bool = True
    ) -> WriteResult:
        if not plan.moves:
            return WriteResult(ok=True, message="Lineup already optimal; nothing to submit.")

        payload = build_lineup_payload(
            plan, self.settings.team_id, scoring_period, self.settings.swid
        )
        if dry_run:
            return WriteResult(
                submitted=len(plan.moves), ok=True, message="Dry run: nothing submitted."
            )

        url = WRITE_URL.format(year=self.settings.year, league_id=self.settings.league_id)
        cookies = {"espn_s2": self.settings.espn_s2, "SWID": self.settings.swid}
        response = requests.post(url, json=payload, cookies=cookies, headers=_HEADERS, timeout=20)

        ok = response.status_code in (200, 201)
        message = "Submitted." if ok else (
            f"ESPN rejected the change (HTTP {response.status_code}): {response.text[:300]}"
        )
        return WriteResult(
            submitted=len(plan.moves),
            status_code=response.status_code,
            ok=ok,
            message=message,
        )


class AddDropWriter:
    """Submits a single add/drop (free-agent pickup paired with a drop) to ESPN.

    Same guardrails as ``LineupWriter``: dry-run is the default (builds the payload, sends
    nothing). A real add/drop is destructive (the dropped player can be claimed), so callers
    only run it on explicit confirmation and verify by re-reading the roster afterwards.
    """

    def __init__(self, settings: config.Settings | None = None):
        self.settings = settings or config.get_settings(require_cookies=True)
        if not self.settings.has_cookies:
            raise WriteError("No ESPN cookies; run `python setup_cookies.py` first.")

    def add_drop(
        self, add_id: int, drop_id: int, scoring_period: int, *, dry_run: bool = True
    ) -> WriteResult:
        payload = build_add_drop_payload(
            add_id, drop_id, self.settings.team_id, scoring_period, self.settings.swid
        )
        if dry_run:
            return WriteResult(submitted=1, ok=True, message="Dry run: nothing submitted.")

        url = WRITE_URL.format(year=self.settings.year, league_id=self.settings.league_id)
        cookies = {"espn_s2": self.settings.espn_s2, "SWID": self.settings.swid}
        response = requests.post(url, json=payload, cookies=cookies, headers=_HEADERS, timeout=20)

        ok = response.status_code in (200, 201)
        message = "Submitted." if ok else (
            f"ESPN rejected the add/drop (HTTP {response.status_code}): {response.text[:300]}"
        )
        return WriteResult(submitted=1, status_code=response.status_code, ok=ok, message=message)
