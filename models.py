"""Shared, library-agnostic data model.

The espn-api ``Player`` object is rich but tied to ESPN's JSON shape. We map it into a
small ``RosterPlayer`` dataclass so the analysis code (and its tests) never depends on
espn-api internals and can be exercised with hand-built fixtures.
"""
from __future__ import annotations

import datetime as dt
import unicodedata
from dataclasses import dataclass, field

# Lineup slot strings (from espn_api POSITION_MAP) that are NOT active scoring slots.
BENCH_SLOT = "BE"
IL_SLOT = "IL"
INACTIVE_SLOTS = {"BE", "IL", "NA"}

# Pitcher lineup slots.
PITCHER_SLOTS = {"P", "SP", "RP"}

# Hitter lineup slots (everything that isn't a pitcher/bench/IL slot).
HITTER_SLOTS = {
    "C", "1B", "2B", "3B", "SS", "OF", "LF", "CF", "RF",
    "DH", "UTIL", "2B/SS", "1B/3B", "IF", "MI", "CI",
}

# ESPN injuryStatus values that mean the player cannot play today.
OUT_STATUSES = {
    "OUT", "SUSPENSION", "INJURY_RESERVE",
    "SEVEN_DAY_DL", "TEN_DAY_DL", "FIFTEEN_DAY_DL", "SIXTY_DAY_DL",
}

# Stat categories where a LOWER value is better (for category-league scoring).
LOWER_IS_BETTER = {
    "ERA", "WHIP", "OBA", "OOBP", "L", "P_BB", "P_IBB", "B_SO",
    "CS", "GDP", "ER", "P_R", "P_HR", "BLSV", "WP", "HBP", "E", "P_H",
}


@dataclass
class RosterPlayer:
    """A normalized view of one player on a roster or in the free-agent pool."""

    player_id: int
    name: str
    pro_team: str                       # ESPN abbrev, e.g. "NYY"
    position: str                       # default position, e.g. "SP", "OF"
    eligible_slots: list[str]           # slots the player qualifies for (incl. UTIL/P/IF...)
    lineup_slot: str = ""               # current slot ("" if unknown)
    injury_status: str = "ACTIVE"
    injured: bool = False
    projected_points: float = 0.0
    projected_stats: dict[str, float] = field(default_factory=dict)  # ESPN season projection
    season_stats: dict[str, float] = field(default_factory=dict)     # actual season-to-date
    percent_owned: float = 0.0
    acquisition_date: dt.date | None = None   # when this player joined the roster (None = unknown)
    acquisition_type: str = ""                # ESPN type, e.g. "DRAFT", "ADD", "TRADE"

    @property
    def is_pitcher(self) -> bool:
        return bool(set(self.eligible_slots) & PITCHER_SLOTS) or self.position in {"SP", "RP"}

    @property
    def is_hitter(self) -> bool:
        return bool(set(self.eligible_slots) & HITTER_SLOTS)

    @property
    def is_out(self) -> bool:
        return self.injured or (self.injury_status or "ACTIVE") in OUT_STATUSES

    def eligible_for(self, slot: str) -> bool:
        return slot in self.eligible_slots


_SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "v"}


def normalize_name(name: str | None) -> str:
    """Lowercase, strip accents/punctuation/suffixes -- for fuzzy name matching."""
    if not name:
        return ""
    text = unicodedata.normalize("NFKD", name)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.lower().replace(".", " ").replace("-", " ").replace("'", "")
    tokens = [t for t in text.split() if t not in _SUFFIXES]
    return " ".join(tokens)
