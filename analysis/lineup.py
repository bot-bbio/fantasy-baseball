"""Daily lineup optimizer.

Given a roster, the league's active-slot shape, and today's MLB schedule, decide the
best legal lineup: start players who actually play today and aren't injured, fill the
scarcest slots first, bench the rest, and park the injured on the IL.

The output is a *target assignment* (player -> slot) plus the minimal set of moves to
get there. The browser layer executes the moves; nothing here touches ESPN.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

from analysis.scoring import compute_category_scores, player_value
from data.mlb_schedule import DaySchedule
from models import (
    BENCH_SLOT,
    IL_SLOT,
    INACTIVE_SLOTS,
    RosterPlayer,
    normalize_name,
)


@dataclass
class Move:
    player_id: int
    name: str
    from_slot: str
    to_slot: str

    def __str__(self) -> str:
        return f"{self.name}: {self.from_slot} -> {self.to_slot}"


@dataclass
class LineupPlan:
    assignments: dict[int, str]          # player_id -> target slot
    moves: list[Move] = field(default_factory=list)
    benched_today: list[str] = field(default_factory=list)
    empty_slots: list[str] = field(default_factory=list)

    @property
    def has_changes(self) -> bool:
        return bool(self.moves)


def is_probable_today(player: RosterPlayer, schedule: DaySchedule) -> bool:
    probable = schedule.probable_pitcher(player.pro_team)
    return bool(probable) and normalize_name(probable) == normalize_name(player.name)


def can_fill_today(player: RosterPlayer, slot: str, schedule: DaySchedule) -> bool:
    """Can this player legally and usefully fill `slot` *today*?"""
    if not player.eligible_for(slot) or player.is_out:
        return False
    plays = schedule.team_plays(player.pro_team)
    if slot == "SP":
        return is_probable_today(player, schedule)
    if slot == "RP":
        return plays
    if slot == "P":  # generic pitcher slot: today's starter, or an available reliever
        return is_probable_today(player, schedule) or ("RP" in player.eligible_slots and plays)
    return plays  # hitter slot: just needs a game today


def expand_active_slots(slot_counts: dict[str, int]) -> list[str]:
    """Flatten {'OF': 3, 'C': 1, ...} into ['OF','OF','OF','C', ...], excluding bench/IL."""
    slots: list[str] = []
    for name, count in slot_counts.items():
        if name in INACTIVE_SLOTS:
            continue
        slots.extend([name] * count)
    return slots


def optimize_lineup(
    roster: list[RosterPlayer],
    slot_counts: dict[str, int],
    schedule: DaySchedule,
    *,
    is_points: bool = True,
    categories: tuple[str, ...] = (),
    now: dt.datetime | None = None,
) -> LineupPlan:
    """Compute the optimal target lineup and the moves needed to reach it.

    Players whose MLB game has already started are *locked* by ESPN and cannot be moved,
    so they're pinned to their current slot and excluded from reassignment.
    """
    now = now or dt.datetime.now(dt.timezone.utc)
    active_slots = expand_active_slots(slot_counts)
    il_count = slot_counts.get(IL_SLOT, 0)

    category_scores = None if is_points else compute_category_scores(roster, categories)

    def value(player: RosterPlayer) -> float:
        return player_value(player, is_points, category_scores)

    bench_count = slot_counts.get(BENCH_SLOT, 0)
    assignments: dict[int, str] = {}
    assigned: set[int] = set()
    remaining = list(active_slots)

    def greedy_fill(slots: list[str], eligible, limit: int | None = None) -> list[str]:
        """Fill slots, scarcest first, with the highest-value eligible player.

        `eligible(player, slot)` decides candidacy. Stops after `limit` placements (or
        when no slot can be filled). Returns the still-unfilled slots.
        """
        slots = list(slots)
        placed = 0
        while slots and (limit is None or placed < limit):
            target_idx: int | None = None
            target_slot = ""
            candidates: list[RosterPlayer] = []
            for idx, slot in enumerate(slots):
                slot_candidates = [
                    p for p in roster
                    if p.player_id not in assigned and eligible(p, slot)
                ]
                if not slot_candidates:
                    continue
                if target_idx is None or len(slot_candidates) < len(candidates):
                    target_idx, target_slot, candidates = idx, slot, slot_candidates
            if target_idx is None:
                break
            chosen = max(candidates, key=value)
            assignments[chosen.player_id] = target_slot
            assigned.add(chosen.player_id)
            slots.pop(target_idx)
            placed += 1
        return slots

    # 1. Pin locked players (game already started) to their current slot, consuming its
    # capacity so the rest is assigned around them.
    for player in roster:
        if schedule.has_started(player.pro_team, now):
            current = player.lineup_slot or BENCH_SLOT
            assignments[player.player_id] = current
            assigned.add(player.player_id)
            if current in remaining:
                remaining.remove(current)

    # 2. Fill the IL with injured, IL-eligible players (prefer those already on the IL to
    # avoid churn), accounting for any locked players already pinned there.
    il_used = sum(1 for slot in assignments.values() if slot == IL_SLOT)
    il_candidates = [
        p for p in roster
        if p.player_id not in assigned and p.is_out and IL_SLOT in p.eligible_slots
    ]
    il_candidates.sort(key=lambda p: p.lineup_slot != IL_SLOT)
    for player in il_candidates[: max(0, il_count - il_used)]:
        assignments[player.player_id] = IL_SLOT
        assigned.add(player.player_id)

    # 3. Fill active slots with players who can actually play today (best first).
    remaining = greedy_fill(remaining, lambda p, slot: can_fill_today(p, slot, schedule))

    # 4. The bench has limited capacity. If more players would land on the bench than fit,
    # force the overflow into the remaining active slots (by eligibility, healthy only) --
    # a full roster can't leave an active slot empty while overflowing the bench.
    locked_on_bench = sum(1 for slot in assignments.values() if slot == BENCH_SLOT)
    unplaced = sum(1 for p in roster if p.player_id not in assigned)
    overflow = max(0, unplaced + locked_on_bench - bench_count)
    if overflow:
        remaining = greedy_fill(
            remaining,
            lambda p, slot: p.eligible_for(slot) and not p.is_out,
            limit=overflow,
        )

    empty_slots = list(remaining)

    # 5. Everyone still unplaced benches.
    for player in roster:
        assignments.setdefault(player.player_id, BENCH_SLOT)

    moves = [
        Move(p.player_id, p.name, p.lineup_slot or BENCH_SLOT, assignments[p.player_id])
        for p in roster
        if (p.lineup_slot or BENCH_SLOT) != assignments[p.player_id]
    ]
    benched_today = [
        p.name for p in roster if assignments[p.player_id] == BENCH_SLOT
    ]
    return LineupPlan(assignments, moves, benched_today, empty_slots)
