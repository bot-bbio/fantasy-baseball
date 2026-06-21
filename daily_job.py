"""Scheduled morning job.

Auto-sets the daily lineup (your chosen autonomy) and writes a Markdown report with
the lineup result plus waiver/streaming recommendations (ask-first, not executed).
Designed to be run by Windows Task Scheduler -- see scheduler_setup.md.

    python daily_job.py
"""
from __future__ import annotations

import datetime as dt

import config
import pipeline
from data import mlb_schedule
from espn_client.reader import LeagueReader


def _execute_lineup(plan, settings, scoring_period) -> list[str]:
    """Auto-apply the lineup via the API; return human-readable status lines."""
    if not plan.has_changes:
        return ["Lineup already optimal - no changes."]

    from espn_client.writer import LineupWriter, WriteError

    try:
        result = LineupWriter(settings).set_lineup(plan, scoring_period, dry_run=False)
    except WriteError as exc:
        return [f"! Auto-apply failed ({exc}). Proposed moves (apply manually):"] \
            + [f"- {m}" for m in plan.moves]

    if result.ok:
        return [f"Applied {result.submitted} moves automatically."] \
            + [f"- {m}" for m in plan.moves]
    return [f"! {result.message} Proposed moves (apply manually):"] \
        + [f"- {m}" for m in plan.moves]


def _drop_cell(rec) -> str:
    """Drop cell for the report, flagging whether it recycles the streamer slot."""
    if rec.drop is None:
        return "-"
    tag = "streamer slot" if rec.drop_is_streamer else "NEW slot"
    return f"{rec.drop.name} ({tag})"


def _render(team_name, lineup_lines, streams, hitters, when) -> str:
    out = [f"# Daily report - {when:%Y-%m-%d %H:%M}", "", f"**Team:** {team_name}", ""]
    out += ["## Lineup", ""] + lineup_lines + [""]

    out += ["## Streaming pitchers", "",
            "_Score = talent + recent form + matchup + park (+ two-start bonus)._",
            "_Drop: 'streamer slot' recycles a tracked streamer; 'NEW slot' would become "
            "your streamer slot (your core arms are never proposed as a drop)._", ""]
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

    out += ["## Best available hitters", ""]
    if hitters:
        out += ["| Add | Team | Drop | Gain |", "|---|---|---|---|"]
        out += [f"| {r.add.name} | {r.add.pro_team} | "
                f"{r.drop.name if r.drop else '-'} | {r.value_gain:.1f} |" for r in hitters]
    else:
        out += ["_No clear upgrades available._"]
    out += ["", "_Adds/drops are recommendations only (ask-first)._"]
    return "\n".join(out)


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
        lineup_lines = _execute_lineup(plan, settings, reader.scoring_period)
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

    report = _render(team_name, lineup_lines, streams, hitters, now)
    path = _write_report(report, today)
    print(report)
    print(f"\nReport: {path}")
    subject = f"Fantasy Baseball {now:%b %d}: {len(plan.moves)} lineup moves, {len(streams)} streamers"
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
