"""Tests for the research layer parsers (pure, no network)."""
from __future__ import annotations

from data.mlb_offense import parse_platoon
from research.fangraphs import parse_rows
from research.research import Research, deep_links


def test_fangraphs_parse_strips_html_and_extracts_metrics():
    rows = [{
        "Name": '<a href="statss.aspx?playerid=22201&position=P">MacKenzie Gore</a>',
        "Team": '<a href="leaders.aspx?team=23">WSH</a>',
        "ERA": 4.07, "FIP": 3.54, "xFIP": 4.03, "SIERA": 4.02,
        "K/9": 9.86, "BB/9": 3.96, "K-BB%": 0.153, "WHIP": 1.30, "GS": 16, "IP": 84,
    }]
    out = parse_rows(rows)
    metrics = out["mackenzie gore"]
    assert metrics["name"] == "MacKenzie Gore"
    assert metrics["fangraphs_id"] == 22201
    assert metrics["SIERA"] == 4.02
    assert metrics["KBB"] == 0.153
    assert metrics["GS"] == 16


def test_parse_platoon_splits():
    data = {"stats": [{"splits": [
        {"team": {"id": 120}, "split": {"code": "vl"}, "stat": {"ops": ".801"}},
        {"team": {"id": 120}, "split": {"code": "vr"}, "stat": {"ops": ".720"}},
    ]}]}
    platoon = parse_platoon(data)
    assert platoon[120] == {"L": 0.801, "R": 0.720}


def test_research_platoon_lookup():
    r = Research(season=2026, platoon={136: {"L": 0.600, "R": 0.800}})
    assert r.opponent_platoon_ops(136, "L") == 0.600
    assert r.opponent_platoon_ops(136, "R") == 0.800
    assert r.opponent_platoon_ops(136, None) is None
    assert r.opponent_platoon_ops(999, "L") is None


def test_deep_links_cover_all_sites():
    links = deep_links("Zac Gallen")
    assert set(links) == {"FanGraphs", "RotoWire", "PitcherList", "FantasyPros"}
    assert all(url.startswith("https://") for url in links.values())
