"""Scheduled morning job.

Builds the optimal lineup and the waiver/add-drop recommendations, then -- instead of
applying anything -- queues every proposed change (the lineup as one item, then each
add/drop) and emails it for confirmation. You reply ``apply all`` / ``apply 1,3`` / ``no``;
the poller (``apply_job.py``) executes only what you approved. Nothing here writes to ESPN.

Designed to be run by Windows Task Scheduler -- see scheduler_setup.md.

    python daily_job.py
"""
from __future__ import annotations

import datetime as dt

import config
import pipeline
from data import mlb_schedule
from espn_client.reader import LeagueReader
from pending import ADD_DROP, LINEUP, PendingQueue

# Keep the approval list short and actionable rather than dumping the whole board.
MAX_STREAMERS = 3
MAX_HITTERS = 3


def _lineup_payload(plan) -> dict:
    return {
        "moves": [
            {"player_id": m.player_id, "name": m.name,
             "from_slot": m.from_slot, "to_slot": m.to_slot}
            for m in plan.moves
        ]
    }


def _streamer_payload(rec) -> dict | None:
    """An executable add/drop payload for a streamer rec, or None if it has no drop."""
    if rec.drop is None:
        return None  # can't execute an add without a drop on a full roster
    add = rec.evaluation.player
    return {
        "add_id": add.player_id, "add_name": add.name, "add_team": add.pro_team,
        "drop_id": rec.drop.player_id, "drop_name": rec.drop.name,
        "drop_is_streamer": rec.drop_is_streamer, "is_streamer_add": True,
        "start_day": rec.evaluation.start_day, "score": round(rec.evaluation.score, 1),
    }


def _hitter_payload(rec) -> dict | None:
    if rec.drop is None:
        return None
    return {
        "add_id": rec.add.player_id, "add_name": rec.add.name, "add_team": rec.add.pro_team,
        "drop_id": rec.drop.player_id, "drop_name": rec.drop.name,
        "drop_is_streamer": False, "is_streamer_add": False,
        "start_day": None, "score": None,
    }


def build_queue(plan, streams, hitters, *, path=None) -> PendingQueue:
    """Turn the lineup plan + recommendations into a numbered, confirmable queue."""
    queue = PendingQueue.new(path=path)

    if plan.has_changes:
        queue.add(LINEUP, f"Set optimal lineup ({len(plan.moves)} move(s))",
                  _lineup_payload(plan))

    for rec in streams[:MAX_STREAMERS]:
        payload = _streamer_payload(rec)
        if payload is None:
            continue
        tag = "recycles streamer slot" if rec.drop_is_streamer else "opens NEW streamer slot"
        queue.add(ADD_DROP,
                  f"ADD {payload['add_name']} ({payload['add_team']}) / "
                  f"DROP {payload['drop_name']} - stream, {tag}", payload)

    for rec in hitters[:MAX_HITTERS]:
        payload = _hitter_payload(rec)
        if payload is None:
            continue
        queue.add(ADD_DROP,
                  f"ADD {payload['add_name']} ({payload['add_team']}) / "
                  f"DROP {payload['drop_name']} - hitter upgrade", payload)

    return queue


def _render_pending(queue: PendingQueue) -> list[str]:
    out = ["## Pending changes - reply to approve", ""]
    if queue.is_empty:
        out += ["_Nothing to change today: lineup is optimal and no upgrades found._", ""]
        return out
    out += [
        f"Reply to this email to apply. Token: `{queue.token}`.",
        "",
        "- `apply all` - apply every item below",
        "- `apply 1,3` or `apply 1-2` - apply only those items",
        "- `no` - discard (apply nothing)",
        "",
        "Nothing is sent to ESPN until you reply.",
        "",
    ]
    for item in queue.items:
        out.append(f"**{item.n}. {item.description}**")
        if item.kind == LINEUP:
            for m in item.payload.get("moves", []):
                out.append(f"    - {m['name']}: {m['from_slot']} -> {m['to_slot']}")
        out.append("")
    return out


def _render(team_name, queue, plan, streams, hitters, when) -> str:
    out = [f"# Daily report - {when:%Y-%m-%d %H:%M}", "", f"**Team:** {team_name}", ""]
    out += _render_pending(queue)

    if plan.empty_slots:
        out += [f"> ! Could not fill: {', '.join(plan.empty_slots)} "
                "(no one available today).", ""]

    out += ["## Streaming pitchers (rationale)", "",
            "_Score = talent + recent form + matchup + park (+ two-start bonus)._", ""]
    if streams:
        out += ["| Add | Team | Score | Talent | Form | Matchup | Drop | Gain |",
                "|---|---|---|---|---|---|---|---|"]
        for s in streams:
            e = s.evaluation
            out.append(
                f"| {e.player.name} | {e.player.pro_team} | {e.score:.0f} | "
                f"{e.talent:.0f} | {e.form:.0f} | {e.summary} | "
                f"{_drop_cell(s)} | {s.value_gain:.1f} |"
            )
        out += ["", "**Verify the model** (research links):"]
        for s in streams:
            if s.evaluation.links:
                joined = " · ".join(f"[{k}]({v})" for k, v in s.evaluation.links.items())
                out.append(f"- {s.evaluation.player.name}: {joined}")
    else:
        out += ["_None worth streaming right now._"]
    out += [""]

    out += ["## Best available hitters (rationale)", ""]
    if hitters:
        out += ["| Add | Team | Drop | Gain |", "|---|---|---|---|"]
        out += [f"| {r.add.name} | {r.add.pro_team} | "
                f"{r.drop.name if r.drop else '-'} | {r.value_gain:.1f} |" for r in hitters]
    else:
        out += ["_No clear upgrades available._"]
    out += [""]
    return "\n".join(out)


def _drop_cell(rec) -> str:
    """Drop cell for the report, flagging whether it recycles the streamer slot."""
    if rec.drop is None:
        return "-"
    tag = "streamer slot" if rec.drop_is_streamer else "NEW slot"
    return f"{rec.drop.name} ({tag})"


def _write_report(text: str, day: dt.date) -> str:
    config.REPORTS_DIR.mkdir(exist_ok=True)
    path = config.REPORTS_DIR / f"{day:%Y-%m-%d}.md"
    path.write_text(text, encoding="utf-8")
    return str(path)


def main() -> int:
    now = dt.datetime.now()
    try:
        settings = config.get_settings(require_cookies=True)
    except config.ConfigError as exc:
        print(f"Config error: {exc}")
        return 2

    reader = LeagueReader(settings)
    try:
        today = config.local_today(settings.timezone)
        schedule = mlb_schedule.fetch_day(today)
        plan, _ = pipeline.build_lineup_plan(reader, schedule)
        schedules = pipeline.upcoming_schedules(settings.timezone, days=2)
        streams, hitters = pipeline.gather_waiver_recs(reader, schedules)
        team_name = reader.my_team().team_name
    except Exception as exc:  # produce a report instead of failing silently
        report = f"# Daily report - {now:%Y-%m-%d %H:%M}\n\n! Run failed: {exc}\n"
        path = _write_report(report, now.date())
        print(report)
        print(f"\nReport: {path}")
        _notify(settings, f"Fantasy Baseball {now:%b %d}: run FAILED", report)
        return 1

    queue = build_queue(plan, streams, hitters)
    if queue.is_empty:
        config.PENDING_FILE.unlink(missing_ok=True)  # no stale queue lingering
    else:
        queue.save()

    report = _render(team_name, queue, plan, streams, hitters, now)
    path = _write_report(report, today)
    print(report)
    print(f"\nReport: {path}")

    if queue.is_empty:
        subject = f"Fantasy Baseball {now:%b %d}: nothing to approve"
    else:
        subject = (f"Fantasy Baseball {now:%b %d}: "
                   f"{len(queue.items)} change(s) to approve [FB {queue.token}]")
    _notify(settings, subject, report)
    return 0


def _notify(settings, subject: str, body: str) -> None:
    """Email the summary if configured; never let a notification error fail the run."""
    if not settings.email_enabled:
        return
    try:
        from notify import send_email
        send_email(subject, body, settings)
        print("Email notification sent.")
    except Exception as exc:
        print(f"! Email notification failed: {exc}")


if __name__ == "__main__":
    raise SystemExit(main())
