"""Streamer-slot tracking.

We churn pitchers for spot starts ("streamers"). To automate add/drops safely the system
has to remember *which* rostered pitcher is the disposable streamer, so a new pickup
recycles that slot instead of accidentally dropping a core arm (an ace having a bad
stretch can look like the "weakest" pitcher on raw skill, which is exactly the trap).

The state is a small, git-ignored JSON log of pitchers we picked up as streamers, ordered
oldest-first (newest appended last). ``current()`` returns the most recent streamer still
on the roster -- the slot a new streamer should replace. Entries for pitchers no longer
rostered are pruned by ``sync()`` so the log self-heals after a drop.

This is deliberately I/O-light and dependency-free so it can be unit-tested against a
temp file with no network and no espn-api.
"""
from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass, field
from pathlib import Path

import config
from models import RosterPlayer


@dataclass
class StreamerLog:
    """An ordered log of streamer pickups (oldest first), persisted as JSON."""

    path: Path
    entries: list[dict] = field(default_factory=list)

    # --- persistence -----------------------------------------------------------------

    @classmethod
    def load(cls, path: Path | None = None) -> "StreamerLog":
        """Load the log; a missing or unreadable file yields an empty log (never raises)."""
        path = path or config.STREAMERS_FILE
        entries: list[dict] = []
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(data, dict) and isinstance(data.get("streamers"), list):
                    entries = [e for e in data["streamers"] if isinstance(e, dict) and "player_id" in e]
            except (json.JSONDecodeError, OSError):
                entries = []
        return cls(path=path, entries=entries)

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps({"streamers": self.entries}, indent=2), encoding="utf-8"
        )

    # --- queries ---------------------------------------------------------------------

    def ids(self) -> set[int]:
        """Player ids currently tracked as streamer slots."""
        return {int(e["player_id"]) for e in self.entries}

    def is_streamer(self, player_id: int) -> bool:
        return int(player_id) in self.ids()

    def current(self, roster_ids: set[int] | None = None) -> int | None:
        """The most recent streamer still on the roster -- the slot to recycle next."""
        for entry in reversed(self.entries):
            pid = int(entry["player_id"])
            if roster_ids is None or pid in roster_ids:
                return pid
        return None

    # --- mutations (caller persists via save()) --------------------------------------

    def record_add(
        self,
        player: RosterPlayer,
        *,
        start_day: str | None = None,
        score: float | None = None,
        dropped: str | None = None,
        on: dt.date | None = None,
    ) -> None:
        """Record that ``player`` was streamed in. Re-adding refreshes (and re-dates) it."""
        self.record_drop(player.player_id)  # de-dupe; a re-add moves it to newest
        self.entries.append(
            {
                "player_id": int(player.player_id),
                "name": player.name,
                "pro_team": player.pro_team,
                "added_on": (on or dt.date.today()).isoformat(),
                "start_day": start_day,
                "score": round(score, 1) if score is not None else None,
                "dropped": dropped,
            }
        )

    def record_drop(self, player_id: int) -> None:
        """Forget a streamer (it was dropped, or otherwise left the roster)."""
        pid = int(player_id)
        self.entries = [e for e in self.entries if int(e["player_id"]) != pid]

    def sync(self, roster: list[RosterPlayer]) -> bool:
        """Prune streamers no longer on ``roster``. Returns True if anything changed."""
        roster_ids = {p.player_id for p in roster}
        before = len(self.entries)
        self.entries = [e for e in self.entries if int(e["player_id"]) in roster_ids]
        return len(self.entries) != before
