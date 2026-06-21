"""Tests for the streamer-slot log (pure, temp-file backed, no network)."""
from __future__ import annotations

import datetime as dt

from streamer_state import StreamerLog
from tests.factories import pitcher


def _log(tmp_path):
    return StreamerLog(path=tmp_path / "streamers.json")


def test_record_add_tracks_player(tmp_path):
    log = _log(tmp_path)
    log.record_add(pitcher(10, "Reid Detmers", team="LAA"), start_day="2026-06-22", score=60.0)
    assert log.ids() == {10}
    assert log.is_streamer(10)
    assert log.current({10}) == 10


def test_current_is_most_recent_still_rostered(tmp_path):
    log = _log(tmp_path)
    log.record_add(pitcher(1, "First In"))
    log.record_add(pitcher(2, "Second In"))
    # Newest still on the roster is the slot to recycle.
    assert log.current({1, 2}) == 2
    # If the newest was dropped from the roster, fall back to the older one.
    assert log.current({1}) == 1
    # None tracked on the roster -> no slot.
    assert log.current({99}) is None


def test_record_drop_forgets_streamer(tmp_path):
    log = _log(tmp_path)
    log.record_add(pitcher(5, "Gone Soon"))
    log.record_drop(5)
    assert log.ids() == set()
    assert log.current({5}) is None


def test_re_add_refreshes_and_dedupes(tmp_path):
    log = _log(tmp_path)
    log.record_add(pitcher(1, "A"))
    log.record_add(pitcher(2, "B"))
    log.record_add(pitcher(1, "A"))  # re-add A -> moves to newest, no duplicate
    assert len(log.entries) == 2
    assert [e["player_id"] for e in log.entries] == [2, 1]
    assert log.current({1, 2}) == 1


def test_sync_prunes_off_roster_streamers(tmp_path):
    log = _log(tmp_path)
    log.record_add(pitcher(1, "Kept"))
    log.record_add(pitcher(2, "Dropped Manually"))
    changed = log.sync([pitcher(1, "Kept")])  # player 2 no longer rostered
    assert changed is True
    assert log.ids() == {1}
    assert log.sync([pitcher(1, "Kept")]) is False  # nothing left to prune


def test_persistence_round_trip(tmp_path):
    log = _log(tmp_path)
    log.record_add(pitcher(7, "Persist Me", team="SD"), on=dt.date(2026, 6, 20))
    log.save()

    reloaded = StreamerLog.load(tmp_path / "streamers.json")
    assert reloaded.ids() == {7}
    entry = reloaded.entries[0]
    assert entry["name"] == "Persist Me"
    assert entry["added_on"] == "2026-06-20"


def test_load_missing_file_is_empty(tmp_path):
    log = StreamerLog.load(tmp_path / "nope.json")
    assert log.entries == []
    assert log.ids() == set()
