"""Tests for the lineup write payload builder (no network)."""
from __future__ import annotations

import pytest

from analysis.lineup import LineupPlan, Move
from espn_client.writer import WriteError, build_add_drop_payload, build_lineup_payload


def _plan(moves):
    return LineupPlan(assignments={}, moves=moves)


def test_payload_maps_slots_to_ids():
    plan = _plan([
        Move(101, "Shohei Ohtani", "BE", "UTIL"),   # 16 -> 12
        Move(202, "Nick Martinez", "BE", "P"),       # 16 -> 13
        Move(303, "Brent Rooker", "UTIL", "BE"),     # 12 -> 16
    ])
    payload = build_lineup_payload(plan, team_id=3, scoring_period=80, swid="{ABC}")

    assert payload["type"] == "ROSTER"
    assert payload["teamId"] == 3
    assert payload["scoringPeriodId"] == 80
    assert payload["memberId"] == "{ABC}"
    assert payload["executionType"] == "EXECUTE"

    items = {i["playerId"]: i for i in payload["items"]}
    assert items[101]["fromLineupSlotId"] == 16 and items[101]["toLineupSlotId"] == 12
    assert items[202]["toLineupSlotId"] == 13
    assert items[303]["fromLineupSlotId"] == 12 and items[303]["toLineupSlotId"] == 16
    assert all(i["type"] == "LINEUP" for i in payload["items"])


def test_unknown_slot_raises():
    plan = _plan([Move(1, "Bad", "BE", "ZZ")])
    with pytest.raises(WriteError):
        build_lineup_payload(plan, team_id=3, scoring_period=80, swid="{ABC}")


def test_add_drop_payload_shape():
    payload = build_add_drop_payload(
        add_id=555, drop_id=222, team_id=3, scoring_period=80, swid="{ABC}"
    )
    assert payload["type"] == "FREEAGENT"
    assert payload["teamId"] == 3
    assert payload["scoringPeriodId"] == 80
    assert payload["memberId"] == "{ABC}"
    assert payload["executionType"] == "EXECUTE"
    assert payload["bidAmount"] == 0

    by_type = {i["type"]: i for i in payload["items"]}
    assert by_type["ADD"]["playerId"] == 555
    assert by_type["ADD"]["toTeamId"] == 3 and by_type["ADD"]["fromTeamId"] == 0
    assert by_type["DROP"]["playerId"] == 222
    assert by_type["DROP"]["fromTeamId"] == 3 and by_type["DROP"]["toTeamId"] == 0
