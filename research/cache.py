"""Tiny on-disk JSON cache so external sources are hit at most ~once per day.

Keeps the daily job and CLI fast and polite to FanGraphs/MLB. Cache files live in
`.cache/` (git-ignored).
"""
from __future__ import annotations

import datetime as dt
import json

import config

CACHE_DIR = config.PROJECT_ROOT / ".cache"


def get(key: str, max_age_hours: float = 18.0):
    """Return cached value for `key` if present and fresh, else None."""
    path = CACHE_DIR / f"{key}.json"
    if not path.exists():
        return None
    age_hours = (dt.datetime.now().timestamp() - path.stat().st_mtime) / 3600
    if age_hours > max_age_hours:
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None


def put(key: str, value) -> None:
    CACHE_DIR.mkdir(exist_ok=True)
    (CACHE_DIR / f"{key}.json").write_text(json.dumps(value), encoding="utf-8")
