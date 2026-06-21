"""Advanced pitcher metrics from the FanGraphs leaders JSON API.

The legacy scrape endpoint is blocked (403), but the JSON API responds fine with a normal
User-Agent. We pull season metrics (and an optional date range for recent form), parse the
HTML-wrapped name/team fields, and cache per day.

Keyed by normalized player name so the streaming model can join by name.
"""
from __future__ import annotations

import re

import requests

from models import normalize_name
from research import cache

API_URL = "https://www.fangraphs.com/api/leaders/major-league/data"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) FantasyBaseball/1.0"}
_TAG = re.compile(r"<[^>]+>")
_PLAYERID = re.compile(r"playerid=(\d+)")


def _clean(text: str | None) -> str:
    return _TAG.sub("", text or "").strip()


def _num(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_rows(rows: list[dict]) -> dict[str, dict]:
    """Pure parser: FanGraphs API rows -> {normalized_name: metrics}."""
    out: dict[str, dict] = {}
    for row in rows:
        raw_name = row.get("Name", "")
        name = _clean(raw_name)
        if not name:
            continue
        fg_id = None
        if match := _PLAYERID.search(raw_name or ""):
            fg_id = int(match.group(1))
        out[normalize_name(name)] = {
            "name": name,
            "fangraphs_id": fg_id,
            "ERA": _num(row.get("ERA")),
            "FIP": _num(row.get("FIP")),
            "xFIP": _num(row.get("xFIP")),
            "SIERA": _num(row.get("SIERA")),
            "K9": _num(row.get("K/9")),
            "BB9": _num(row.get("BB/9")),
            "KBB": _num(row.get("K-BB%")),
            "WHIP": _num(row.get("WHIP")),
            "GS": _num(row.get("GS")),
            "IP": _num(row.get("IP")),
        }
    return out


def pitcher_metrics(
    season: int, *, start: str | None = None, end: str | None = None,
    qual: str = "0", timeout: int = 45,
) -> dict[str, dict]:
    """Season (or date-range) advanced pitching metrics, cached daily."""
    span = f"{start}_{end}" if start and end else "season"
    key = f"fangraphs_pit_{season}_{span}"
    cached = cache.get(key)
    if cached is not None:
        return cached

    params = {
        "pos": "all", "stats": "pit", "lg": "all", "qual": qual,
        "season": str(season), "season1": str(season), "month": "0", "team": "0",
        "pageitems": "100000", "pagenum": "1", "ind": "0", "type": "8",
    }
    if start and end:
        params.update({"startdate": start, "enddate": end, "month": "1000"})

    response = requests.get(API_URL, params=params, headers=HEADERS, timeout=timeout)
    response.raise_for_status()
    rows = response.json().get("data", [])
    metrics = parse_rows(rows)
    cache.put(key, metrics)
    return metrics
