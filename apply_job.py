"""Scheduled approval poller.

Checks the agent Gmail for your reply to the daily proposal and applies exactly what you
approved, then emails the result. Run it on a short interval (e.g. every 20 minutes) via
Task Scheduler -- see scheduler_setup.md. Safe to run when there's nothing to do (it just
exits). ``cli.py poll`` runs the same ``poll_once`` once, on demand.

    python apply_job.py
"""
from __future__ import annotations

import datetime as dt

import apply
import config
import inbox
from espn_client.reader import LeagueReader
from pending import PendingQueue


def _notify(settings: config.Settings, subject: str, body: str) -> None:
    """Email a result if configured; never let a notification error fail the poll."""
    if not settings.email_enabled:
        return
    try:
        from notify import send_email
        send_email(subject, body, settings)
    except Exception as exc:
        print(f"! Email notification failed: {exc}")


def _should_fallback(settings: config.Settings, queue: PendingQueue) -> bool:
    """True if the opt-in lineup safety net should fire (no reply, queue too old)."""
    minutes = settings.lineup_fallback_minutes
    if minutes is None or not queue.lineup_items():
        return False
    age = queue.age_minutes()
    return age is not None and age >= minutes


def _apply_lineup_fallback(settings: config.Settings, queue: PendingQueue) -> str:
    """Auto-apply only the lineup items, leaving any add/drops pending for a real reply."""
    reader = LeagueReader(settings)
    lineup_items = queue.lineup_items()
    lines = apply.apply_selection(lineup_items, reader=reader, settings=settings)

    remaining = [i for i in queue.items if i.kind != "LINEUP"]
    if remaining:
        for n, item in enumerate(remaining, start=1):  # renumber so 'apply 1,2' still works
            item.n = n
        queue.items = remaining
        queue.save()
        tail = ("\n\nAdd/drops are still awaiting your reply (apply all / apply 1,3 / no).")
    else:
        queue.consume()
        tail = ""
    body = (f"Lineup auto-applied: no reply within {settings.lineup_fallback_minutes} min "
            f"(LINEUP_FALLBACK_MINUTES).\n\n" + "\n".join(lines) + tail)
    _notify(settings, "Fantasy Baseball: lineup auto-applied (fallback)", body)
    return body


def poll_once(settings: config.Settings) -> str:
    """One inbox check -> apply -> notify cycle. Returns a console summary."""
    queue = PendingQueue.load()
    if queue is None:
        return "No pending queue; nothing to poll."

    if queue.is_expired():
        queue.consume()
        return "Pending queue expired (>24h); discarded."

    try:
        reply = inbox.fetch_reply(settings, queue.token)
    except Exception as exc:  # transient IMAP/login error -- try again next poll
        return f"Could not read inbox (will retry next poll): {exc}"

    if reply is None:
        if _should_fallback(settings, queue):
            return _apply_lineup_fallback(settings, queue)
        return "No matching reply yet; leaving the queue pending."

    if reply.selection is None:
        _notify(settings, "Fantasy Baseball: didn't understand your reply",
                "I couldn't read a command in your reply. Reply with one of:\n"
                "  apply all      apply 1,3      no\n\n"
                f"Your message was:\n{reply.body[:500]}")
        return "Reply received but unparseable; asked the user to retry. Queue kept."

    if reply.selection == "none":
        queue.consume()
        _notify(settings, "Fantasy Baseball: changes discarded",
                "Okay -- discarded today's proposed changes. Nothing was applied.")
        return "User declined; queue discarded."

    items = queue.select(reply.selection)
    reader = LeagueReader(settings)
    lines = apply.apply_selection(items, reader=reader, settings=settings)
    queue.consume()
    body = "Applied your approved changes:\n\n" + "\n".join(lines)
    _notify(settings, "Fantasy Baseball: changes applied", body)
    return body


def main() -> int:
    now = dt.datetime.now()
    try:
        settings = config.get_settings(require_cookies=True)
    except config.ConfigError as exc:
        print(f"Config error: {exc}")
        return 2
    try:
        summary = poll_once(settings)
    except Exception as exc:  # never crash a scheduled task
        print(f"! Poll failed: {exc}")
        _notify(settings, f"Fantasy Baseball {now:%b %d}: poll FAILED", str(exc))
        return 1
    print(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
