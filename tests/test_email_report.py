"""Tests for the phone-friendly email rendering."""
from __future__ import annotations

import datetime as dt

from analysis.budget import AcquisitionBudget
from analysis.lineup import LineupPlan, Move
from analysis.streaming import StreamerEvaluation, StreamerRecommendation
from analysis.waivers import Recommendation
from email_report import render_email
from pending import ADD_DROP, LINEUP, PendingQueue
from tests.factories import hitter, pitcher

WHEN = dt.datetime(2026, 6, 22, 8, 0)


def _budget(remaining):
    if remaining is None:
        return AcquisitionBudget.unlimited()
    return AcquisitionBudget(season_used=0, season_limit=None,
                             period_used=0, period_limit=remaining, period_label="today")


def _stream_rec(*, start_label="Tomorrow", days_out=1, gain=19.4, is_upgrade=True,
                has_drop=True, staff_gain=8.0):
    add = pitcher(100, "Andre Pallante", team="StL")
    drop = pitcher(1, "Nick Martinez", team="Cin") if has_drop else None
    ev = StreamerEvaluation(
        player=add, start_day="2026-06-22", opponent="Twins", opponent_ops=0.690,
        park_factor=100, talent=55, form=60, matchup=58, park=50, score=58.0,
        links={"FanGraphs": "https://example.com/fg"},
        start_label=start_label, days_out=days_out,
    )
    return StreamerRecommendation(ev, drop, gain, drop_is_streamer=False,
                                  is_upgrade=is_upgrade, staff_gain=staff_gain)


def _hitter_rec():
    add = hitter(200, "Eugenio Suarez", team="Cin")
    drop = hitter(3, "Jose Caballero", team="NYY")
    return Recommendation(add, drop, "Upgrade over Jose Caballero", 6.2)


def _queue(*items):
    q = PendingQueue.new(path=None)
    for kind, desc, payload in items:
        q.add(kind, desc, payload)
    return q


def test_renders_text_and_html():
    queue = _queue((ADD_DROP, "ADD Andre Pallante (StL) / DROP Nick Martinez - stream", {}))
    text, html = render_email("The Bronx Unabombers", queue, LineupPlan(assignments={}),
                              [_stream_rec()], [_hitter_rec()], WHEN, _budget(1), held_back=1)

    # Both non-empty and carry the key content.
    assert "Andre Pallante" in text and "Andre Pallante" in html
    assert "apply all" in text and "apply all" in html
    assert "The Bronx Unabombers".upper() in text
    assert html.lstrip().startswith("<div")


def test_text_has_no_markdown_table_or_symbols():
    """The whole point: a phone reads plain text, so no pipe-tables or markdown noise."""
    queue = _queue((ADD_DROP, "ADD Andre Pallante (StL) / DROP Nick Martinez", {}))
    text, _ = render_email("Team", queue, LineupPlan(assignments={}),
                           [_stream_rec()], [_hitter_rec()], WHEN, _budget(1), held_back=0)
    assert "|---|" not in text
    assert "|" not in text                       # no table columns at all
    assert "**" not in text                      # no markdown bold markers
    assert "##" not in text                      # no markdown headers


def test_held_back_note_appears_only_when_trimmed():
    queue = _queue((ADD_DROP, "ADD A / DROP B", {}))
    streams, hitters, plan = [_stream_rec()], [_hitter_rec()], LineupPlan(assignments={})

    text_trim, html_trim = render_email("T", queue, plan, streams, hitters, WHEN,
                                        _budget(1), held_back=2)
    assert "not queued" in text_trim and "not queued" in html_trim

    text_ok, html_ok = render_email("T", queue, plan, streams, hitters, WHEN,
                                    _budget(None), held_back=0)
    assert "not queued" not in text_ok and "not queued" not in html_ok


def test_empty_queue_says_nothing_to_change():
    empty = PendingQueue.new(path=None)
    text, html = render_email("Team", empty, LineupPlan(assignments={}),
                              [], [], WHEN, _budget(1), held_back=0)
    assert "Nothing to change" in text
    assert "All set" in html


def test_lineup_moves_are_listed():
    plan = LineupPlan(assignments={}, moves=[Move(9, "Willy Adames", "SS", "BE")])
    queue = _queue((LINEUP, "Set optimal lineup (1 move(s))",
                    {"moves": [{"name": "Willy Adames", "from_slot": "SS", "to_slot": "BE"}]}))
    text, html = render_email("T", queue, plan, [], [], WHEN, _budget(1), held_back=0)
    assert "Willy Adames" in text and "SS -> BE" in text
    assert "Willy Adames" in html


def test_two_way_prompt_appears_in_email():
    plan = LineupPlan(assignments={}, two_way_pitching=["Shohei Ohtani"], empty_slots=["UTIL"])
    queue = PendingQueue.new(path=None)
    text, html = render_email("T", queue, plan, [], [], WHEN, _budget(1), held_back=0)
    assert "Shohei Ohtani is pitching today" in text
    assert "Shohei Ohtani is pitching today" in html
    assert "add a hitter" in text.lower()


def test_start_date_is_highlighted():
    """The probable start date shows in both parts, as an amber pill in the HTML."""
    queue = _queue((ADD_DROP, "ADD Andre Pallante (StL) / DROP Nick Martinez", {}))
    text, html = render_email("T", queue, LineupPlan(assignments={}),
                              [_stream_rec()], [], WHEN, _budget(None), held_back=0)
    assert "Tomorrow" in text
    assert "Tomorrow" in html
    assert "#fff3cd" in html                     # the amber date-pill background rendered


def test_planahead_note_only_for_starts_beyond_horizon():
    plan = LineupPlan(assignments={})
    imminent = render_email("T", PendingQueue.new(path=None), plan,
                            [_stream_rec(start_label="Tomorrow", days_out=1)], [],
                            WHEN, _budget(None), held_back=0)
    for part in imminent:
        assert "plan ahead" not in part          # today/tomorrow starts: no note

    far = render_email("T", PendingQueue.new(path=None), plan,
                       [_stream_rec(start_label="Fri Jul 10", days_out=4)], [],
                       WHEN, _budget(None), held_back=0)
    for part in far:
        assert "plan ahead" in part               # a start days out is flagged as plan-ahead


def test_landscape_shows_upgrades_and_scouting_options():
    """The whole available landscape renders: upgrades are marked and show their swap,
    a worse-than-your-arm option shows its negative gain, and an option with no open drop
    is shown for reference instead of being hidden."""
    upgrade = _stream_rec(is_upgrade=True, gain=12.0, staff_gain=6.0)  # beats the arm it'd drop
    below = _stream_rec(is_upgrade=False, gain=-4.0, staff_gain=-9.0)  # has a drop, but worse
    no_slot = _stream_rec(is_upgrade=False, has_drop=False, staff_gain=3.0)  # no disposable arm
    plan = LineupPlan(assignments={})
    text, html = render_email("T", PendingQueue.new(path=None), plan,
                              [upgrade, below, no_slot], [], WHEN, _budget(None), held_back=0)

    assert "UPGRADE" in text and "upgrade" in html          # upgrade tag present
    assert "+12.0" in text and "+12.0" in html              # upgrade slot gain, signed
    assert "-4.0" in text and "-4.0" in html                # below-arm negative slot gain, signed
    assert "no open drop" in text and "no open drop" in html  # scouting-only option surfaced
    assert "vs staff" in text and "vs staff" in html        # staff-value metric shown too
    assert "+6.0" in text and "+6.0" in html                # staff gain, signed


def test_html_escapes_special_characters():
    add = hitter(200, "Tom & Jerry", team="NYY")
    drop = hitter(3, "A<b>C", team="Bos")
    rec = Recommendation(add, drop, "x", 1.0)
    queue = PendingQueue.new(path=None)
    _, html = render_email("T", queue, LineupPlan(assignments={}), [], [rec],
                           WHEN, _budget(None), held_back=0)
    assert "Tom &amp; Jerry" in html       # '&' escaped, not injected raw
    assert "A&lt;b&gt;C" in html           # the drop name's literal <b> is neutralized
    assert "A<b>C" not in html             # ...and never appears unescaped
