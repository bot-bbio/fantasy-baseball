"""Tests for the change executor (fake writers/reader -- no network, no espn-api)."""
from __future__ import annotations

import apply
import config
from espn_client.writer import WriteResult
from pending import ADD_DROP, LINEUP, PendingItem
from streamer_state import StreamerLog
from tests.factories import hitter


SETTINGS = config.Settings(
    league_id=1, year=2026, team_id=3, timezone="UTC", espn_s2="s2", swid="{S}"
)


class FakeReader:
    scoring_period = 80


class FakeLineupWriter:
    def __init__(self):
        self.calls = []

    def set_lineup(self, plan, scoring_period, *, dry_run=True):
        self.calls.append((plan, scoring_period, dry_run))
        return WriteResult(submitted=len(plan.moves), ok=True, message="Submitted.")


class FakeAddDropWriter:
    def __init__(self, ok=True):
        self.calls = []
        self.ok = ok

    def add_drop(self, add_id, drop_id, scoring_period, *, dry_run=True):
        self.calls.append((add_id, drop_id, scoring_period, dry_run))
        return WriteResult(submitted=1, ok=self.ok,
                           message="Submitted." if self.ok else "rejected")


def _lineup_item(n=1):
    return PendingItem(n, LINEUP, "Set optimal lineup (1 move(s))",
                       {"moves": [{"player_id": 1, "name": "A",
                                   "from_slot": "BE", "to_slot": "UTIL"}]})


def _add_item(n, add_id, drop_id, *, streamer=False):
    return PendingItem(n, ADD_DROP, f"ADD {add_id} / DROP {drop_id}",
                       {"add_id": add_id, "add_name": f"A{add_id}", "add_team": "NYY",
                        "drop_id": drop_id, "drop_name": f"D{drop_id}",
                        "is_streamer_add": streamer, "start_day": "2026-06-22",
                        "score": 61.0})


def _apply(items, *, log, flw=None, fadw=None, verify=False):
    return apply.apply_selection(
        items, reader=FakeReader(), settings=SETTINGS,
        lineup_writer=flw or FakeLineupWriter(),
        addrop_writer=fadw or FakeAddDropWriter(), log=log, verify=verify,
    )


def test_empty_selection_applies_nothing(tmp_path):
    log = StreamerLog(path=tmp_path / "s.json")
    assert _apply([], log=log) == ["No changes approved - nothing applied."]


def test_lineup_item_submits_real_write(tmp_path):
    log = StreamerLog(path=tmp_path / "s.json")
    flw = FakeLineupWriter()
    lines = _apply([_lineup_item()], log=log, flw=flw)
    assert flw.calls and flw.calls[0][1] == 80 and flw.calls[0][2] is False  # dry_run False
    assert any("Lineup OK" in ln for ln in lines)


def test_streamer_add_records_in_log(tmp_path):
    log = StreamerLog(path=tmp_path / "s.json")
    fadw = FakeAddDropWriter()
    lines = _apply([_add_item(1, add_id=10, drop_id=20, streamer=True)], log=log, fadw=fadw)
    assert fadw.calls[0][:2] == (10, 20)
    assert log.ids() == {10}  # the added streamer is now tracked
    assert any("OK" in ln for ln in lines)


def test_drop_of_tracked_streamer_is_forgotten(tmp_path):
    log = StreamerLog(path=tmp_path / "s.json")
    log.record_add(hitter(20, "Old Streamer", team="SD", position="SP", slots=("SP", "P")))
    _apply([_add_item(1, add_id=10, drop_id=20, streamer=True)], log=log)
    assert 20 not in log.ids() and log.ids() == {10}


def test_hitter_add_does_not_track_streamer(tmp_path):
    log = StreamerLog(path=tmp_path / "s.json")
    _apply([_add_item(1, add_id=30, drop_id=40, streamer=False)], log=log)
    assert log.ids() == set()  # non-streamer adds are not tracked


def test_duplicate_drop_is_skipped(tmp_path):
    log = StreamerLog(path=tmp_path / "s.json")
    fadw = FakeAddDropWriter()
    items = [_add_item(1, add_id=10, drop_id=99), _add_item(2, add_id=11, drop_id=99)]
    lines = _apply(items, log=log, fadw=fadw)
    assert len(fadw.calls) == 1  # second add/drop never submitted
    assert any("skipped" in ln for ln in lines)


def test_failed_write_does_not_track_or_block_others(tmp_path):
    log = StreamerLog(path=tmp_path / "s.json")
    fadw = FakeAddDropWriter(ok=False)
    lines = _apply([_add_item(1, add_id=10, drop_id=20, streamer=True)], log=log, fadw=fadw)
    assert log.ids() == set()  # nothing recorded on a rejected write
    assert any("FAILED" in ln for ln in lines)


def test_verify_confirms_changes_via_reread(tmp_path, monkeypatch):
    class VerifyReader:
        def __init__(self, settings):
            pass

        def roster(self):
            # Player 1 now in UTIL (lineup applied); 10 added; 20 gone.
            return [hitter(1, "A", slot="UTIL"), hitter(10, "A10", slot="BE")]

    monkeypatch.setattr(apply, "LeagueReader", VerifyReader)
    log = StreamerLog(path=tmp_path / "s.json")
    items = [_lineup_item(1), _add_item(2, add_id=10, drop_id=20, streamer=True)]
    lines = _apply(items, log=log, verify=True)
    assert any("Verified via re-read" in ln for ln in lines)
