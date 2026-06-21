"""Tests for best-available hitter recommendations."""
from __future__ import annotations

from analysis.waivers import find_best_available_hitters
from tests.factories import hitter


def test_best_available_hitter_upgrade():
    roster = [hitter(1, "Weak Bat", team="NYY", slots=("OF", "UTIL"), pts=3)]
    free_agents = [
        hitter(100, "Hot Bat", team="Bos", slots=("OF", "UTIL"), pts=25),
        hitter(101, "Cold Bat", team="Bos", slots=("OF", "UTIL"), pts=1),
    ]
    recs = find_best_available_hitters(roster, free_agents, is_points=True)
    assert len(recs) == 1
    assert recs[0].add.player_id == 100
    assert recs[0].drop.player_id == 1


def test_no_upgrade_returns_empty():
    roster = [hitter(1, "Stud", team="NYY", slots=("OF", "UTIL"), pts=80)]
    free_agents = [hitter(100, "Scrub", team="Bos", slots=("OF", "UTIL"), pts=2)]
    assert find_best_available_hitters(roster, free_agents, is_points=True) == []
