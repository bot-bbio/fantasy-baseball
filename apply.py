"""Execute approved changes from the pending queue.

Shared by the e-mail poller (``apply_job.py`` / ``cli.py poll``) and the manual
``cli.py apply`` path, so both apply changes identically. Each selected item maps to one
ESPN write; a failure on one item is reported but never aborts the rest. After writing we
re-read the roster to *verify* what actually changed, mirroring ``cli.cmd_lineup``.

Only items already in the queue can be applied -- the selection chooses among them, it never
describes a new move (see ``pending`` / ``inbox``).
"""
from __future__ import annotations

import config
from analysis.lineup import LineupPlan, Move
from espn_client.reader import LeagueReader
from espn_client.writer import AddDropWriter, LineupWriter, WriteError, WriteResult
from models import RosterPlayer
from pending import ADD_DROP, LINEUP, PendingItem
from streamer_state import StreamerLog


def _plan_from_payload(payload: dict) -> LineupPlan:
    moves = [
        Move(int(m["player_id"]), str(m.get("name", "")), str(m["from_slot"]), str(m["to_slot"]))
        for m in payload.get("moves", [])
    ]
    return LineupPlan(assignments={}, moves=moves)


def _apply_lineup(item: PendingItem, writer: LineupWriter, scoring_period: int) -> tuple[bool, str]:
    plan = _plan_from_payload(item.payload)
    if not plan.moves:
        return True, f"[{item.n}] Lineup already optimal - nothing to submit."
    try:
        result = writer.set_lineup(plan, scoring_period, dry_run=False)
    except WriteError as exc:
        return False, f"[{item.n}] Lineup FAILED to submit: {exc}"
    status = "OK" if result.ok else "FAILED"
    return result.ok, f"[{item.n}] Lineup {status}: {result.submitted} move(s). {result.message}"


def _apply_add_drop(
    item: PendingItem, writer: AddDropWriter, scoring_period: int, log: StreamerLog
) -> tuple[bool, str]:
    p = item.payload
    add_id, drop_id = int(p["add_id"]), int(p["drop_id"])
    try:
        result = writer.add_drop(add_id, drop_id, scoring_period, dry_run=False)
    except WriteError as exc:
        return False, f"[{item.n}] {item.description} FAILED: {exc}"
    if result.ok:
        _record_streamer_change(item, log)
    status = "OK" if result.ok else "FAILED"
    return result.ok, f"[{item.n}] {item.description} {status}. {result.message}"


def _record_streamer_change(item: PendingItem, log: StreamerLog) -> None:
    """Keep the streamer-slot log in step after a successful add/drop."""
    p = item.payload
    log.record_drop(int(p["drop_id"]))  # forget the dropped pitcher if it was tracked
    if p.get("is_streamer_add"):
        added = RosterPlayer(
            player_id=int(p["add_id"]), name=str(p.get("add_name", "")),
            pro_team=str(p.get("add_team", "")), position="SP", eligible_slots=["SP", "P"],
        )
        log.record_add(added, start_day=p.get("start_day"), score=p.get("score"),
                       dropped=p.get("drop_name"))


def apply_selection(
    items: list[PendingItem],
    *,
    reader: LeagueReader,
    settings: config.Settings,
    lineup_writer: LineupWriter | None = None,
    addrop_writer: AddDropWriter | None = None,
    log: StreamerLog | None = None,
    verify: bool = True,
) -> list[str]:
    """Execute the selected items in order; return human-readable result lines.

    A drop is applied at most once per batch: if two approved items would drop the same
    player (e.g. two streamers sharing one slot), the later one is skipped and noted, since
    the player is already gone after the first.
    """
    if not items:
        return ["No changes approved - nothing applied."]

    lineup_writer = lineup_writer or LineupWriter(settings)
    addrop_writer = addrop_writer or AddDropWriter(settings)
    log = log if log is not None else StreamerLog.load()
    scoring_period = reader.scoring_period

    lines: list[str] = []
    spent_drops: set[int] = set()
    spent_adds: set[int] = set()
    applied_lineup = False
    applied_add_drop = False
    log_dirty = False

    for item in items:
        if item.kind == LINEUP:
            ok, line = _apply_lineup(item, lineup_writer, scoring_period)
            applied_lineup = applied_lineup or ok
            lines.append(line)
        elif item.kind == ADD_DROP:
            add_id, drop_id = int(item.payload["add_id"]), int(item.payload["drop_id"])
            if drop_id in spent_drops or add_id in spent_adds:
                lines.append(f"[{item.n}] {item.description} skipped "
                             "(player already added/dropped earlier in this batch).")
                continue
            ok, line = _apply_add_drop(item, addrop_writer, scoring_period, log)
            if ok:
                spent_drops.add(drop_id)
                spent_adds.add(add_id)
                applied_add_drop = True
                log_dirty = True
            lines.append(line)
        else:
            lines.append(f"[{item.n}] Unknown change kind {item.kind!r}; skipped.")

    if log_dirty:
        log.save()
    if verify and (applied_lineup or applied_add_drop):
        lines += _verify(settings, items, check_lineup=applied_lineup, check_add_drop=applied_add_drop)
    return lines


def _verify(settings, items, *, check_lineup: bool, check_add_drop: bool) -> list[str]:
    """Re-read the roster and confirm the writes landed (fresh reader -> no stale cache)."""
    try:
        roster = LeagueReader(settings).roster()
    except Exception as exc:  # verification is best-effort; never mask a successful write
        return [f"(Could not verify via re-read: {exc})"]

    slot_by_id = {p.player_id: p.lineup_slot for p in roster}
    ids_on_roster = set(slot_by_id)
    problems: list[str] = []

    if check_lineup:
        for item in (i for i in items if i.kind == LINEUP):
            for move in item.payload.get("moves", []):
                pid, want = int(move["player_id"]), str(move["to_slot"])
                if slot_by_id.get(pid) != want:
                    problems.append(f"  - {move.get('name', pid)} expected in {want}, "
                                    f"is in {slot_by_id.get(pid, 'off roster')!r}")
    if check_add_drop:
        for item in (i for i in items if i.kind == ADD_DROP):
            p = item.payload
            if int(p["add_id"]) not in ids_on_roster:
                problems.append(f"  - {p.get('add_name', p['add_id'])} not on roster after add")
            if int(p["drop_id"]) in ids_on_roster:
                problems.append(f"  - {p.get('drop_name', p['drop_id'])} still on roster after drop")

    if problems:
        return ["! Verification found mismatches (ESPN may have rejected part):", *problems]
    return ["Verified via re-read: all approved changes are reflected on ESPN."]
