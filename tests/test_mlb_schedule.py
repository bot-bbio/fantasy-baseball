"""Tests for the MLB Stats API schedule parser (pure, no network)."""
from __future__ import annotations

from data.mlb_schedule import parse_schedule

SAMPLE = {
    "dates": [
        {
            "games": [
                {
                    "status": {"detailedState": "Scheduled"},
                    "teams": {
                        "home": {
                            "team": {"id": 147, "name": "New York Yankees"},
                            "probablePitcher": {"fullName": "Gerrit Cole"},
                        },
                        "away": {
                            "team": {"id": 111, "name": "Boston Red Sox"},
                            "probablePitcher": {"fullName": "Brayan Bello"},
                        },
                    },
                },
                {
                    "status": {"detailedState": "Postponed"},
                    "teams": {
                        "home": {"team": {"id": 121, "name": "New York Mets"}},
                        "away": {"team": {"id": 143, "name": "Philadelphia Phillies"}},
                    },
                },
            ]
        }
    ]
}


def test_parse_extracts_playing_teams_and_probables():
    schedule = parse_schedule(SAMPLE, "2026-06-20")
    assert schedule.playing_team_ids == {147, 111}        # postponed game excluded
    assert schedule.probable_pitchers[147] == "Gerrit Cole"
    assert schedule.probable_pitchers[111] == "Brayan Bello"


def test_team_plays_maps_espn_abbrev():
    schedule = parse_schedule(SAMPLE, "2026-06-20")
    assert schedule.team_plays("NYY") is True      # 147
    assert schedule.team_plays("Bos") is True      # 111
    assert schedule.team_plays("NYM") is False     # postponed
    assert schedule.probable_pitcher("NYY") == "Gerrit Cole"
