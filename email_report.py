"""Phone-first rendering of the daily report for email.

The saved ``reports/*.md`` file stays Markdown (great on a computer), but Markdown read as
*plain text* on a phone is rough: literal ``#``/``**`` and, worst of all, wide ``| col |``
tables that don't wrap on a narrow screen. This module renders the same data two ways for
a multipart email instead:

  - **HTML** -- a single-column, big-text, tappable-link layout that phone mail clients
    render nicely (inline styles only; email clients strip <style>/external CSS).
  - **plain text** -- a vertical, short-line fallback with no Markdown noise or tables.

``render_email(...)`` returns ``(text, html)``. The action block (what to approve and how
to reply) comes first so it's the first thing you see on the train; the rationale follows.
"""
from __future__ import annotations

import datetime as dt
from html import escape

import config
from analysis.budget import AcquisitionBudget
from pending import LINEUP, PendingQueue

# Inline styles, kept as named fragments so the markup below stays readable.
_FONT = "font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif"
_WRAP = (f"{_FONT};max-width:560px;margin:0 auto;padding:16px;"
         "color:#1a1a1a;font-size:17px;line-height:1.5")
_CARD = ("border:1px solid #e3e3e3;border-radius:10px;padding:12px 14px;"
         "margin:10px 0;background:#fafafa")
_ACTION = ("border:1px solid #cfe6cf;border-radius:10px;padding:14px 16px;"
           "margin:12px 0;background:#f1f8f1")
_BADGE = ("display:inline-block;min-width:22px;height:22px;line-height:22px;"
          "text-align:center;border-radius:11px;background:#2e7d32;color:#fff;"
          "font-size:14px;font-weight:700;margin-right:8px")
_MUTED = "color:#666;font-size:14px"
_H2 = "font-size:15px;text-transform:uppercase;letter-spacing:.04em;color:#888;margin:22px 0 4px"
_CMD = "background:#eee;border-radius:5px;padding:1px 6px;font-weight:700;white-space:nowrap"
# Highlighted probable-start-date pill (amber = "when", distinct from the green score).
_DATE = ("display:inline-block;background:#fff3cd;color:#7a5b00;border:1px solid #ffe69c;"
         "border-radius:6px;padding:1px 8px;font-size:14px;font-weight:700;white-space:nowrap")


def _moves_lines(item) -> list[str]:
    return [f"{m['name']}: {m['from_slot']} -> {m['to_slot']}"
            for m in item.payload.get("moves", [])]


def _held_note(budget: AcquisitionBudget, held_back: int) -> str | None:
    if not held_back:
        return None
    moves = "move" if budget.remaining == 1 else f"{budget.remaining} moves"
    return (f"Only the top {moves} fit today's add/drop budget; "
            f"{held_back} more upgrade(s) are listed below but not queued.")


def _planahead_note(streams) -> str | None:
    """Clarify that starts past the queueing horizon are for planning, not queued yet."""
    horizon = config.STREAM_QUEUE_HORIZON_DAYS
    if not any((s.evaluation.days_out or 0) > horizon for s in streams):
        return None
    edge = "today" if horizon <= 0 else "tomorrow" if horizon == 1 else f"{horizon} days out"
    return f"Starts beyond {edge} are shown to plan ahead and aren't queued yet."


# --------------------------------------------------------------------------------------
# Plain-text part
# --------------------------------------------------------------------------------------

def _text(team_name, queue, plan, streams, hitters, when, budget, held_back) -> str:
    when_str = when.strftime("%a, %b %d") if hasattr(when, "strftime") else str(when)
    out = [team_name.upper(), when_str, ""]

    if queue.is_empty:
        out += ["Nothing to change today: lineup is optimal and no add/drops are "
                "within budget.", ""]
    else:
        n = len(queue.items)
        out += [f"=== {n} CHANGE{'S' if n != 1 else ''} TO APPROVE ===",
                "Reply:  apply all   /   apply 1,3   /   no",
                f"Add/drop budget: {budget.describe()}. "
                "Nothing is sent to ESPN until you reply.", ""]
        for item in queue.items:
            out.append(f"{item.n}. {item.description}")
            if item.kind == LINEUP:
                out += [f"     {line}" for line in _moves_lines(item)]
        out.append("")

    note = _held_note(budget, held_back)
    if note:
        out += [f"({note})", ""]

    if plan.two_way_prompt():
        out += [f">> {plan.two_way_prompt()}", ""]

    if plan.empty_slots:
        out += [f"! Could not fill: {', '.join(plan.empty_slots)} (no one available today).",
                ""]

    out += ["--- STREAMING OPTIONS ---"]
    if streams:
        for s in streams:
            e = s.evaluation
            head = f"* {e.player.name} ({e.player.pro_team})"
            if e.start_label:
                head += f" - STARTS {e.start_label}"
            out += [head,
                    f"    score {e.score:.0f}, {e.summary}",
                    f"    drop {_drop_text(s)}, gain +{s.value_gain:.1f}"]
        note = _planahead_note(streams)
        if note:
            out.append(f"  ({note})")
    else:
        out.append("(none worth streaming right now)")
    out.append("")

    out += [f"--- BEST HITTER UPGRADE{'S' if len(hitters) != 1 else ''} ---"]
    if hitters:
        for r in hitters:
            drop = r.drop.name if r.drop else "-"
            out.append(f"* {r.add.name} ({r.add.pro_team}) -> drop {drop}, gain +{r.value_gain:.1f}")
    else:
        out.append("(no clear upgrades available)")

    return "\n".join(out).rstrip() + "\n"


def _drop_text(s) -> str:
    if s.drop is None:
        return "-"
    tag = "streamer slot" if s.drop_is_streamer else "new slot"
    return f"{s.drop.name} ({tag})"


# --------------------------------------------------------------------------------------
# HTML part
# --------------------------------------------------------------------------------------

def _cmd(text: str) -> str:
    return f'<span style="{_CMD}">{escape(text)}</span>'


def _html(team_name, queue, plan, streams, hitters, when, budget, held_back) -> str:
    when_str = when.strftime("%a, %b %d") if hasattr(when, "strftime") else str(when)
    h = [f'<div style="{_WRAP}">',
         f'<div style="{_MUTED}">{escape(team_name)} · {escape(when_str)}</div>']

    if queue.is_empty:
        h += [f'<div style="{_ACTION}"><b>All set for today.</b><br>'
              f'<span style="{_MUTED}">Lineup is optimal and no add/drops are within '
              'budget.</span></div>']
    else:
        n = len(queue.items)
        h += [f'<h1 style="font-size:21px;margin:14px 0 4px">{n} change{"s" if n != 1 else ""} '
              'to approve</h1>',
              f'<div style="{_ACTION}">Reply with {_cmd("apply all")} · '
              f'{_cmd("apply 1,3")} · {_cmd("no")}'
              f'<div style="{_MUTED};margin-top:6px">Add/drop budget: '
              f'{escape(budget.describe())}. Nothing is sent to ESPN until you reply.'
              '</div></div>']
        for item in queue.items:
            inner = f'<span style="{_BADGE}">{item.n}</span><b>{escape(item.description)}</b>'
            if item.kind == LINEUP:
                lines = "<br>".join(escape(line) for line in _moves_lines(item))
                if lines:
                    inner += f'<div style="{_MUTED};margin:6px 0 0 30px">{lines}</div>'
            h.append(f'<div style="{_CARD}">{inner}</div>')

    note = _held_note(budget, held_back)
    if note:
        h.append(f'<div style="{_MUTED};margin:8px 0">{escape(note)}</div>')

    if plan.two_way_prompt():
        h.append(f'<div style="{_ACTION}">⚾ {escape(plan.two_way_prompt())}</div>')

    if plan.empty_slots:
        h.append(f'<div style="color:#b00;font-size:15px;margin:8px 0">⚠ Could not fill: '
                 f'{escape(", ".join(plan.empty_slots))} (no one available today).</div>')

    h.append(f'<div style="{_H2}">Streaming options</div>')
    if streams:
        for s in streams:
            e = s.evaluation
            links = ""
            if e.links:
                joined = " · ".join(
                    f'<a href="{escape(v)}" style="color:#2e7d32">{escape(k)}</a>'
                    for k, v in e.links.items())
                links = f'<div style="{_MUTED};margin-top:4px">{joined}</div>'
            date_pill = (f' <span style="{_DATE}">▶ {escape(e.start_label)}</span>'
                         if e.start_label else "")
            h.append(
                f'<div style="{_CARD}">'
                f'<b>{escape(e.player.name)}</b> '
                f'<span style="{_MUTED}">({escape(e.player.pro_team)})</span> '
                f'&nbsp;<b style="color:#2e7d32">{e.score:.0f}</b>{date_pill}'
                f'<div style="{_MUTED};margin-top:2px">{escape(e.summary)}</div>'
                f'<div style="margin-top:2px">drop {escape(_drop_text(s))} · '
                f'gain <b>+{s.value_gain:.1f}</b></div>{links}</div>')
        note = _planahead_note(streams)
        if note:
            h.append(f'<div style="{_MUTED};margin:6px 0">{escape(note)}</div>')
    else:
        h.append(f'<div style="{_MUTED}">None worth streaming right now.</div>')

    h.append(f'<div style="{_H2}">Best hitter upgrade{"s" if len(hitters) != 1 else ""}</div>')
    if hitters:
        for r in hitters:
            drop = escape(r.drop.name) if r.drop else "-"
            h.append(
                f'<div style="{_CARD}"><b>{escape(r.add.name)}</b> '
                f'<span style="{_MUTED}">({escape(r.add.pro_team)})</span> → '
                f'drop {drop} · gain <b>+{r.value_gain:.1f}</b></div>')
    else:
        h.append(f'<div style="{_MUTED}">No clear upgrades available.</div>')

    h.append("</div>")
    return "\n".join(h)


def render_email(
    team_name, queue: PendingQueue, plan, streams, hitters,
    when: dt.datetime, budget: AcquisitionBudget, held_back: int,
) -> tuple[str, str]:
    """Return ``(text_body, html_body)`` for a phone-friendly multipart email."""
    args = (team_name, queue, plan, streams, hitters, when, budget, held_back)
    return _text(*args), _html(*args)
