"""Team offensive strength (season OPS) from the MLB Stats API.

Used by the streaming model to judge matchup difficulty: a probable start against a
weak-hitting team is more valuable than the same start against a strong lineup.
"""
from __future__ import annotations

import functools

import requests

STATS_URL = "https://statsapi.mlb.com/api/v1/teams/stats"

# Fallback if a team's OPS is missing or the fetch fails (roughly league average).
DEFAULT_OPS = 0.715


def parse_team_ops(data: dict) -> dict[int, float]:
    """Pure parser: MLB team id -> season OPS."""
    result: dict[int, float] = {}
    for block in data.get("stats", []):
        for split in block.get("splits", []):
            team_id = split.get("team", {}).get("id")
            ops = split.get("stat", {}).get("ops")
            if team_id is None or ops is None:
                continue
            try:
                result[int(team_id)] = float(ops)
            except (TypeError, ValueError):
                continue
    return result


@functools.lru_cache(maxsize=4)
def team_offense_ops(season: int, *, timeout: int = 20) -> dict[int, float]:
    """MLB team id -> season OPS (cached per season for the process)."""
    params = {"stats": "season", "group": "hitting", "season": season, "sportId": 1}
    response = requests.get(STATS_URL, params=params, timeout=timeout)
    response.raise_for_status()
    return parse_team_ops(response.json())


def parse_platoon(data: dict) -> dict[int, dict[str, float]]:
    """Pure parser: team id -> {'L': OPS vs LHP, 'R': OPS vs RHP}."""
    out: dict[int, dict[str, float]] = {}
    for block in data.get("stats", []):
        for split in block.get("splits", []):
            team_id = split.get("team", {}).get("id")
            code = split.get("split", {}).get("code")  # 'vl' = vs LHP, 'vr' = vs RHP
            ops = split.get("stat", {}).get("ops")
            if team_id is None or code not in ("vl", "vr") or ops is None:
                continue
            try:
                out.setdefault(int(team_id), {})["L" if code == "vl" else "R"] = float(ops)
            except (TypeError, ValueError):
                continue
    return out


@functools.lru_cache(maxsize=4)
def team_platoon_ops(season: int, *, timeout: int = 20) -> dict[int, dict[str, float]]:
    """team id -> {'L'/'R': OPS vs that pitcher hand} (one call, cached)."""
    params = {"stats": "statSplits", "group": "hitting", "season": season,
              "sportId": 1, "sitCodes": "vl,vr"}
    response = requests.get(STATS_URL, params=params, timeout=timeout)
    response.raise_for_status()
    return parse_platoon(response.json())


def league_average_ops(ops_by_team: dict[int, float]) -> float:
    return sum(ops_by_team.values()) / len(ops_by_team) if ops_by_team else DEFAULT_OPS
