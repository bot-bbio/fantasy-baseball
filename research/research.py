"""High-level research bundle for the streaming model.

Gathers (and caches) the external signals the model consumes: FanGraphs advanced metrics
(season + recent form), MLB platoon splits, pitcher handedness, plus reference deep-links
for the gated/editorial sites (RotoWire, PitcherList) we don't scrape.

Every fetch is wrapped so a source being down degrades gracefully to the ESPN-based model.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from urllib.parse import quote_plus

import requests

from data import mlb_offense
from models import normalize_name
from research import cache, fangraphs

PEOPLE_URL = "https://statsapi.mlb.com/api/v1/people/{id}"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) FantasyBaseball/1.0"}

# Sites we link to rather than scrape (paywalled / editorial).
_LINK_SITES = {
    "FanGraphs": "fangraphs.com",
    "RotoWire": "rotowire.com",
    "PitcherList": "pitcherlist.com",
    "FantasyPros": "fantasypros.com",
}


def _safe(func, default):
    try:
        return func()
    except Exception:
        return default


@dataclass
class Research:
    season: int
    fg_season: dict = field(default_factory=dict)   # normalized name -> metrics
    fg_recent: dict = field(default_factory=dict)
    platoon: dict = field(default_factory=dict)      # team id -> {'L'/'R': OPS}

    def season_metrics(self, name: str) -> dict | None:
        return self.fg_season.get(normalize_name(name))

    def recent_metrics(self, name: str) -> dict | None:
        return self.fg_recent.get(normalize_name(name))

    def opponent_platoon_ops(self, team_id: int | None, hand: str | None) -> float | None:
        if team_id is None or hand not in ("L", "R"):
            return None
        return self.platoon.get(team_id, {}).get(hand)


def build(season: int, *, recent_days: int = 30) -> Research:
    """Fetch FanGraphs season + recent metrics and MLB platoon splits (cached)."""
    fg_season = _safe(lambda: fangraphs.pitcher_metrics(season, qual="10"), {})
    end = dt.date.today()
    start = end - dt.timedelta(days=recent_days)
    fg_recent = _safe(
        lambda: fangraphs.pitcher_metrics(
            season, start=start.isoformat(), end=end.isoformat(), qual="1"
        ),
        {},
    )
    platoon = _safe(lambda: mlb_offense.team_platoon_ops(season), {})
    return Research(season=season, fg_season=fg_season, fg_recent=fg_recent, platoon=platoon)


def pitcher_hand(mlbam_id: int | None) -> str | None:
    """'L' or 'R' for a pitcher (MLB people endpoint, cached ~30 days)."""
    if not mlbam_id:
        return None
    key = f"hand_{mlbam_id}"
    cached = cache.get(key, max_age_hours=24 * 30)
    if cached is not None:
        return cached.get("hand")
    hand = None
    try:
        resp = requests.get(PEOPLE_URL.format(id=mlbam_id), headers=HEADERS, timeout=15)
        hand = resp.json()["people"][0].get("pitchHand", {}).get("code")
    except Exception:
        hand = None
    cache.put(key, {"hand": hand})
    return hand


def deep_links(name: str) -> dict[str, str]:
    """Site-scoped search links for manual reading (no scraping of gated content)."""
    return {
        label: f"https://www.google.com/search?q={quote_plus(f'site:{domain} {name}')}"
        for label, domain in _LINK_SITES.items()
    }
