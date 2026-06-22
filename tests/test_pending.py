"""Tests for the pending-changes queue (pure, temp-file backed, no network)."""
from __future__ import annotations

import datetime as dt

from pending import ADD_DROP, LINEUP, PendingQueue, parse_numbers


def _queue(tmp_path) -> PendingQueue:
    q = PendingQueue.new(path=tmp_path / "pending.json")
    q.add(LINEUP, "Set optimal lineup (2 move(s))",
          {"moves": [{"player_id": 1, "name": "A", "from_slot": "BE", "to_slot": "UTIL"}]})
    q.add(ADD_DROP, "ADD X / DROP Y",
          {"add_id": 10, "add_name": "X", "add_team": "NYY",
           "drop_id": 20, "drop_name": "Y", "is_streamer_add": True})
    q.add(ADD_DROP, "ADD P / DROP Q",
          {"add_id": 11, "add_name": "P", "drop_id": 21, "drop_name": "Q"})
    return q


def test_new_queue_has_token_and_is_empty(tmp_path):
    q = PendingQueue.new(path=tmp_path / "pending.json")
    assert q.token and len(q.token) == 8  # secrets.token_hex(4)
    assert q.is_empty


def test_add_auto_numbers(tmp_path):
    q = _queue(tmp_path)
    assert [i.n for i in q.items] == [1, 2, 3]
    assert not q.is_empty


def test_round_trip_preserves_items_and_payloads(tmp_path):
    q = _queue(tmp_path)
    q.save()

    reloaded = PendingQueue.load(tmp_path / "pending.json")
    assert reloaded is not None
    assert reloaded.token == q.token
    assert [i.n for i in reloaded.items] == [1, 2, 3]
    assert reloaded.items[0].kind == LINEUP
    assert reloaded.items[1].payload["add_id"] == 10
    assert reloaded.items[1].payload["is_streamer_add"] is True


def test_select_all_none_and_numbers(tmp_path):
    q = _queue(tmp_path)
    assert [i.n for i in q.select("all")] == [1, 2, 3]
    assert q.select("none") == []
    assert [i.n for i in q.select({1, 3})] == [1, 3]
    assert [i.n for i in q.select("1-2")] == [1, 2]
    # Out-of-range numbers are silently ignored.
    assert [i.n for i in q.select({2, 99})] == [2]


def test_lineup_items_filter(tmp_path):
    q = _queue(tmp_path)
    assert [i.n for i in q.lineup_items()] == [1]


def test_expiry(tmp_path):
    q = PendingQueue.new(path=tmp_path / "pending.json")
    now = dt.datetime(2026, 6, 21, 12, 0, tzinfo=dt.timezone.utc)
    q.created = (now - dt.timedelta(hours=25)).isoformat()
    assert q.is_expired(now=now) is True
    q.created = (now - dt.timedelta(hours=1)).isoformat()
    assert q.is_expired(now=now) is False


def test_age_minutes(tmp_path):
    q = PendingQueue.new(path=tmp_path / "pending.json")
    now = dt.datetime(2026, 6, 21, 12, 0, tzinfo=dt.timezone.utc)
    q.created = (now - dt.timedelta(minutes=45)).isoformat()
    assert round(q.age_minutes(now=now)) == 45


def test_consume_removes_file(tmp_path):
    q = _queue(tmp_path)
    q.save()
    assert (tmp_path / "pending.json").exists()
    q.consume()
    assert not (tmp_path / "pending.json").exists()
    # Consuming again (missing file) must not raise.
    q.consume()


def test_load_missing_or_corrupt_is_none(tmp_path):
    assert PendingQueue.load(tmp_path / "nope.json") is None
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    assert PendingQueue.load(bad) is None
    no_token = tmp_path / "notoken.json"
    no_token.write_text('{"items": []}', encoding="utf-8")
    assert PendingQueue.load(no_token) is None


def test_parse_numbers():
    assert parse_numbers("1,3") == {1, 3}
    assert parse_numbers("1-3") == {1, 2, 3}
    assert parse_numbers("apply 2 4") == {2, 4}
    assert parse_numbers("3-1") == {1, 2, 3}  # tolerant of reversed ranges
    assert parse_numbers("none") == set()
