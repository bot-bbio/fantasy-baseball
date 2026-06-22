"""Central configuration.

Loads non-secret settings from ``.env`` and the ESPN auth cookies (captured by
``setup_cookies.py``) from ``.auth/``. These cookies authenticate both the read and
write APIs. Secrets are never printed; error messages refer to *how* to fix a problem,
never the value of a credential.
"""
from __future__ import annotations

import datetime as dt
import json
import os
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent

# Local, git-ignored location for the ESPN auth cookies.
AUTH_DIR = PROJECT_ROOT / ".auth"
COOKIES_FILE = AUTH_DIR / "cookies.json"       # {"espn_s2": ..., "swid": ...}

# Generated output.
REPORTS_DIR = PROJECT_ROOT / "reports"

# Local, git-ignored persistent state (streamer-slot tracking, etc.).
STATE_DIR = PROJECT_ROOT / ".state"
STREAMERS_FILE = STATE_DIR / "streamers.json"
# Queued, awaiting-confirmation changes (lineup + add/drops) the poller may apply.
PENDING_FILE = STATE_DIR / "pending.json"

load_dotenv(PROJECT_ROOT / ".env")


class ConfigError(RuntimeError):
    """Raised when configuration is missing or malformed."""


@dataclass(frozen=True)
class Settings:
    league_id: int
    year: int
    team_id: int
    timezone: str
    espn_s2: str | None
    swid: str | None
    email_sender: str | None = None
    email_app_password: str | None = None
    email_recipient: str | None = None
    imap_host: str = "imap.gmail.com"
    # Address a confirmation reply must come FROM (defaults to the recipient we mailed).
    confirm_from: str | None = None
    # If set, the poller auto-applies *only the lineup* once a queue is this many minutes
    # old with no reply. None (default) means nothing auto-applies -- confirm everything.
    lineup_fallback_minutes: int | None = None

    @property
    def has_cookies(self) -> bool:
        return bool(self.espn_s2 and self.swid)

    @property
    def email_enabled(self) -> bool:
        return bool(self.email_sender and self.email_app_password and self.email_recipient)

    @property
    def confirm_enabled(self) -> bool:
        """Can we read replies? Needs the same mailbox creds plus a sender to trust."""
        return bool(
            self.email_sender and self.email_app_password and self.confirm_address
        )

    @property
    def confirm_address(self) -> str | None:
        """The single address whose replies we honour (confirm_from, else recipient)."""
        return self.confirm_from or self.email_recipient


def _require_int(name: str) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        raise ConfigError(
            f"Missing required setting {name}. Copy .env.example to .env and fill it in."
        )
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigError(f"Setting {name} must be an integer, got {raw!r}.") from exc


def _optional_int(name: str) -> int | None:
    """An int env var that may be blank/absent (returns None), but must parse if present."""
    raw = os.getenv(name, "").strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigError(f"Setting {name} must be an integer, got {raw!r}.") from exc


def load_cookies() -> tuple[str | None, str | None]:
    """Return (espn_s2, swid) from the saved cookie file, or (None, None)."""
    if not COOKIES_FILE.exists():
        return None, None
    data = json.loads(COOKIES_FILE.read_text(encoding="utf-8"))
    return data.get("espn_s2"), data.get("swid")


def save_cookies(espn_s2: str, swid: str) -> None:
    """Persist the ESPN auth cookies (called by setup_cookies)."""
    AUTH_DIR.mkdir(exist_ok=True)
    COOKIES_FILE.write_text(
        json.dumps({"espn_s2": espn_s2, "swid": swid}), encoding="utf-8"
    )


def local_today(timezone: str) -> dt.date:
    """Today's date in the configured timezone (falls back to system local)."""
    try:
        return dt.datetime.now(ZoneInfo(timezone)).date()
    except (ZoneInfoNotFoundError, ValueError):
        return dt.date.today()


def get_settings(require_cookies: bool = False) -> Settings:
    """Build the Settings object.

    Args:
        require_cookies: if True, raise ConfigError when no saved ESPN cookies are present.
    """
    league_id = _require_int("ESPN_LEAGUE_ID")
    team_id = _require_int("ESPN_TEAM_ID")
    year = int(os.getenv("ESPN_YEAR", "2026"))
    timezone = os.getenv("TIMEZONE", "America/Toronto").strip() or "America/Toronto"
    espn_s2, swid = load_cookies()

    settings = Settings(
        league_id=league_id,
        year=year,
        team_id=team_id,
        timezone=timezone,
        espn_s2=espn_s2,
        swid=swid,
        email_sender=os.getenv("EMAIL_SENDER", "").strip() or None,
        # Gmail shows app passwords in groups of four; the real value has no spaces.
        email_app_password="".join(os.getenv("EMAIL_APP_PASSWORD", "").split()) or None,
        email_recipient=os.getenv("EMAIL_RECIPIENT", "").strip() or None,
        imap_host=os.getenv("IMAP_HOST", "").strip() or "imap.gmail.com",
        confirm_from=os.getenv("CONFIRM_FROM", "").strip() or None,
        lineup_fallback_minutes=_optional_int("LINEUP_FALLBACK_MINUTES"),
    )

    if require_cookies and not settings.has_cookies:
        raise ConfigError(
            "No saved ESPN cookies found. Run `python setup_cookies.py` first."
        )
    return settings
