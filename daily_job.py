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
import email_report
import pipeline
from analysis.budget import AcquisitionBudget
from data import mlb_schedule
from espn_client.reader import LeagueReader
from pending import ADD_DROP, LINEUP, PendingQueue

# Keep the approval list short and actionable rather than dumping the whole board.
# The offense is steadier than the pitching staff, so we propose at most one hitter move
# and let streaming -- which is date-sensitive -- take priority for a scarce add/drop.
MAX_STREAMERS = 3
MAX_HITTERS = 1


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
        "start_day": rec.evaluation.start_day, "start_label": rec.evaluation.start_label,
        "days_out": rec.evaluation.days_out, "score": round(rec.evaluation.score, 1),
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


def _is_queueable_stream(rec) -> bool:
    """True if a streamer's start is imminent enough to queue for approval *now*.

    The rolling report surfaces starts several days out for planning, but we only queue an
    add whose start falls within ``STREAM_QUEUE_HORIZON_DAYS`` (today/tomorrow) so we never
    add a pitcher days before he throws -- burning a roster slot and an add/drop early. A
    missing ``days_out`` (unknown date) is treated as imminent to preserve prior behaviour.
    """
    days_out = rec.evaluation.days_out
    return days_out is None or days_out <= config.STREAM_QUEUE_HORIZON_DAYS


def _executable_add_drops(streams, hitters) -> list[tuple[str, dict]]:
    """All proposed add/drops that have an executable payload, in priority order.

    Streaming pitchers come first: a start is date-sensitive (a great matchup today is
    gone tomorrow), whereas a hitter upgrade keeps. So when only a few moves fit the
    league's add/drop budget, the streams win the slot. Only imminent starts are queued
    (see ``_is_queueable_stream``); further-out starts remain in the report to plan ahead.
    """
    items: list[tuple[str, dict]] = []
    queueable = [rec for rec in streams if _is_queueable_stream(rec)]
    for rec in queueable[:MAX_STREAMERS]:
        payload = _streamer_payload(rec)
        if payload is None:
            continue
        tag = "recycles streamer slot" if rec.drop_is_streamer else "opens NEW streamer slot"
        when = f" [starts {payload['start_label']}]" if payload.get("start_label") else ""
        items.append((f"ADD {payload['add_name']} ({payload['add_team']}){when} / "
                      f"DROP {payload['drop_name']} - stream, {tag}", payload))
    for rec in hitters[:MAX_HITTERS]:
        payload = _hitter_payload(rec)
        if payload is None:
            continue
        items.append((f"ADD {payload['add_name']} ({payload['add_team']}) / "
                      f"DROP {payload['drop_name']} - hitter upgrade", payload))
    return items


def build_queue(plan, streams, hitters, budget, *, path=None) -> tuple[PendingQueue, int]:
    """Turn the lineup plan + recommendations into a numbered, confirmable queue.

    The league caps how many add/drops we may make (``budget``). Lineup changes are free,
    but only ``budget.remaining`` add/drops are queued -- the highest-priority ones. The
    second return value is how many executable add/drops were held back by that cap.
    """
    queue = PendingQueue.new(path=path)

    if plan.has_changes:
        queue.add(LINEUP, f"Set optimal lineup ({len(plan.moves)} move(s))",
                  _lineup_payload(plan))

    add_drops = _executable_add_drops(streams, hitters)
    allowed = add_drops if budget.remaining is None else add_drops[: budget.remaining]
    for description, payload in allowed:
        queue.add(ADD_DROP, description, payload)

    return queue, len(add_drops) - len(allowed)


def _render_pending(queue: PendingQueue, budget: AcquisitionBudget, held_back: int) -> list[str]:
    out = ["## Pending changes - reply to approve", "",
           f"**Add/drop budget:** {budget.describe()}.", ""]
    if held_back:
        out += [f"> Only the top {'move' if budget.remaining == 1 else f'{budget.remaining} moves'} "
                f"fit your budget; {held_back} further upgrade(s) are listed below but not queued.",
                ""]
    if queue.is_empty:
        out += ["_Nothing to change today: lineup is optimal and no add/drops are within budget._",
                ""]
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


def _render(team_name, queue, plan, streams, hitters, when, budget, held_back) -> str:
    out = [f"# Daily report - {when:%Y-%m-%d %H:%M}", "", f"**Team:** {team_name}", ""]
    out += _render_pending(queue, budget, held_back)

    if plan.two_way_prompt():
        out += [f"> ⚾ {plan.two_way_prompt()}", ""]

    if plan.empty_slots:
        out += [f"> ! Could not fill: {', '.join(plan.empty_slots)} "
                "(no one available today).", ""]

    out += ["## Streaming pitchers (rationale)", "",
            "_Score = talent + recent form + matchup + park (+ two-start bonus). "
            "**Start** = highlighted probable start date across the rolling look-ahead._", ""]
    if streams:
        out += ["| Add | Team | Start | Score | Talent | Form | Matchup | Drop | Gain |",
                "|---|---|---|---|---|---|---|---|---|"]
        for s in streams:
            e = s.evaluation
            out.append(
                f"| {e.player.name} | {e.player.pro_team} | **{e.start_label or e.start_day}** | "
                f"{e.score:.0f} | {e.talent:.0f} | {e.form:.0f} | {e.summary} | "
                f"{_drop_cell(s)} | {s.value_gain:.1f} |"
            )
        if _has_planahead(streams):
            out += ["", f"> {_planahead_note()}"]
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


def _horizon_edge() -> str:
    """Word for the last day a start may fall on and still be queued now."""
    h = config.STREAM_QUEUE_HORIZON_DAYS
    return "today" if h <= 0 else "tomorrow" if h == 1 else f"{h} days out"


def _planahead_note() -> str:
    return (f"Starts beyond {_horizon_edge()} are shown to plan ahead and aren't queued "
            "yet; only imminent starts are proposed for approval above.")


def _has_planahead(streams) -> bool:
    """True if any surfaced streamer starts past the queueing horizon (plan-ahead only)."""
    return any((s.evaluation.days_out or 0) > config.STREAM_QUEUE_HORIZON_DAYS for s in streams)


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
        schedules = pipeline.upcoming_schedules(
            settings.timezone, days=config.STREAM_LOOKAHEAD_DAYS)
        streams, hitters = pipeline.gather_waiver_recs(reader, schedules)
        budget = _budget(reader)
        team_name = reader.my_team().team_name
    except Exception as exc:  # produce a report instead of failing silently
        report = f"# Daily report - {now:%Y-%m-%d %H:%M}\n\n! Run failed: {exc}\n"
        path = _write_report(report, now.date())
        print(report)
        print(f"\nReport: {path}")
        _notify(settings, f"Fantasy Baseball {now:%b %d}: run FAILED", report)
        return 1

    queue, held_back = build_queue(plan, streams, hitters, budget)
    if queue.is_empty:
        config.PENDING_FILE.unlink(missing_ok=True)  # no stale queue lingering
    else:
        queue.save()

    report = _render(team_name, queue, plan, streams, hitters, now, budget, held_back)
    path = _write_report(report, today)
    print(report)
    print(f"\nReport: {path}")

    if queue.is_empty:
        subject = f"Fantasy Baseball {now:%b %d}: nothing to approve"
    else:
        subject = (f"Fantasy Baseball {now:%b %d}: "
                   f"{len(queue.items)} change(s) to approve [FB {queue.token}]")
    # The saved file keeps the Markdown report; the email gets a phone-friendly rendering.
    text_body, html_body = email_report.render_email(
        team_name, queue, plan, streams, hitters, now, budget, held_back)
    _notify(settings, subject, text_body, html=html_body)
    return 0


def _budget(reader) -> AcquisitionBudget:
    """The league's add/drop budget; an unlimited fallback if ESPN can't be read.

    Never let a budget-fetch error fail the run -- worst case we revert to the prior
    behaviour of proposing every upgrade.
    """
    try:
        return reader.acquisition_budget()
    except Exception as exc:
        print(f"! Could not read add/drop budget ({exc}); assuming unlimited.")
        return AcquisitionBudget.unlimited()


def _notify(settings, subject: str, body: str, *, html: str | None = None) -> None:
    """Email the summary if configured; never let a notification error fail the run."""
    if not settings.email_enabled:
        return
    try:
        from notify import send_email
        send_email(subject, body, settings, html=html)
        print("Email notification sent.")
    except Exception as exc:
        print(f"! Email notification failed: {exc}")


if __name__ == "__main__":
    raise SystemExit(main())
