"""Queued, awaiting-confirmation changes.

Nothing is written to ESPN automatically any more. Each morning the daily job builds a
``PendingQueue`` -- a numbered list of proposed changes (the lineup as one item, then each
add/drop) -- persists it, and emails it. You reply to that email; a poller maps your reply
onto these *pre-computed* items and executes only the ones you approved. A reply can never
introduce a new move: it can only select from this queue, which is the core safety property.

The queue carries a short single-use ``token`` echoed in the email subject. A confirmation
reply must quote that token (Gmail does, in the quoted original), so an old "yes" can't apply
a newer queue, and a stale queue is ignored once ``consume()`` deletes the file.

Like ``streamer_state``, this is deliberately I/O-light and dependency-free so it unit-tests
against a temp file with no network.
"""
from __future__ import annotations

import datetime as dt
import json
import secrets
from dataclasses import asdict, dataclass, field
from pathlib import Path

import config

LINEUP = "LINEUP"
ADD_DROP = "ADD_DROP"


@dataclass
class PendingItem:
    """One approvable change. ``payload`` shape depends on ``kind``.

    LINEUP   -> {"moves": [{"player_id", "name", "from_slot", "to_slot"}, ...]}
    ADD_DROP -> {"add_id", "add_name", "drop_id", "drop_name",
                 "drop_is_streamer", "start_day", "score"}
    """

    n: int
    kind: str
    description: str
    payload: dict = field(default_factory=dict)


@dataclass
class PendingQueue:
    """A numbered set of proposed changes awaiting confirmation, persisted as JSON."""

    token: str
    created: str  # ISO-8601 timestamp (UTC)
    items: list[PendingItem] = field(default_factory=list)
    path: Path = field(default=None, repr=False)  # type: ignore[assignment]

    # --- construction ----------------------------------------------------------------

    @classmethod
    def new(cls, path: Path | None = None) -> "PendingQueue":
        """An empty queue with a fresh single-use token and 'now' timestamp."""
        return cls(
            token=secrets.token_hex(4),
            created=dt.datetime.now(dt.timezone.utc).isoformat(),
            items=[],
            path=path or config.PENDING_FILE,
        )

    def add(self, kind: str, description: str, payload: dict) -> PendingItem:
        """Append an item, auto-numbering it (1-based)."""
        item = PendingItem(n=len(self.items) + 1, kind=kind, description=description,
                           payload=payload)
        self.items.append(item)
        return item

    @property
    def is_empty(self) -> bool:
        return not self.items

    # --- persistence -----------------------------------------------------------------

    @classmethod
    def load(cls, path: Path | None = None) -> "PendingQueue | None":
        """Load the queue; missing/corrupt/structurally-invalid file -> None (never raises)."""
        path = path or config.PENDING_FILE
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None
        if not isinstance(data, dict) or "token" not in data:
            return None
        items = [
            PendingItem(n=int(d["n"]), kind=str(d["kind"]),
                        description=str(d.get("description", "")),
                        payload=dict(d.get("payload", {})))
            for d in data.get("items", [])
            if isinstance(d, dict) and "n" in d and "kind" in d
        ]
        return cls(token=str(data["token"]), created=str(data.get("created", "")),
                   items=items, path=path)

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        body = {
            "token": self.token,
            "created": self.created,
            "items": [asdict(i) for i in self.items],
        }
        self.path.write_text(json.dumps(body, indent=2), encoding="utf-8")

    def consume(self) -> None:
        """Delete the queue file so an approved/cancelled queue can't be applied twice."""
        self.path.unlink(missing_ok=True)

    # --- queries ---------------------------------------------------------------------

    def is_expired(self, max_age_hours: float = 24.0, *, now: dt.datetime | None = None) -> bool:
        """True if the queue is older than ``max_age_hours`` (or its timestamp is unreadable)."""
        now = now or dt.datetime.now(dt.timezone.utc)
        try:
            created = dt.datetime.fromisoformat(self.created)
        except (ValueError, TypeError):
            return True
        if created.tzinfo is None:
            created = created.replace(tzinfo=dt.timezone.utc)
        return (now - created) > dt.timedelta(hours=max_age_hours)

    def age_minutes(self, *, now: dt.datetime | None = None) -> float | None:
        now = now or dt.datetime.now(dt.timezone.utc)
        try:
            created = dt.datetime.fromisoformat(self.created)
        except (ValueError, TypeError):
            return None
        if created.tzinfo is None:
            created = created.replace(tzinfo=dt.timezone.utc)
        return (now - created).total_seconds() / 60.0

    def select(self, spec: str | set[int]) -> list[PendingItem]:
        """Resolve a selection into queue items.

        ``spec`` is "all", "none", or a set of 1-based item numbers (see
        ``parse_numbers``). Out-of-range numbers are ignored. Order follows the queue.
        """
        if spec == "all":
            return list(self.items)
        if spec == "none":
            return []
        wanted = spec if isinstance(spec, set) else parse_numbers(spec)
        return [i for i in self.items if i.n in wanted]

    def lineup_items(self) -> list[PendingItem]:
        return [i for i in self.items if i.kind == LINEUP]


def parse_numbers(text: str) -> set[int]:
    """Parse '1,3' / '1-2' / '2 4' into a set of ints. Tolerant of stray words/punctuation."""
    import re

    nums: set[int] = set()
    for token in re.split(r"[,\s]+", text.strip()):
        if not token:
            continue
        range_match = re.fullmatch(r"(\d+)-(\d+)", token)
        if range_match:
            lo, hi = int(range_match.group(1)), int(range_match.group(2))
            nums.update(range(min(lo, hi), max(lo, hi) + 1))
        elif token.isdigit():
            nums.add(int(token))
    return nums
