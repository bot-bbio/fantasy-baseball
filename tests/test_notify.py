"""Tests for email notification config + message building (no network)."""
from __future__ import annotations

from config import Settings
from notify import build_message, send_email


def _settings(**overrides) -> Settings:
    base = dict(league_id=1, year=2026, team_id=1, timezone="UTC", espn_s2=None, swid=None)
    base.update(overrides)
    return Settings(**base)


def test_email_disabled_when_unconfigured():
    settings = _settings()
    assert settings.email_enabled is False
    assert send_email("subj", "body", settings) is False  # no-op, no network


def test_build_message_sets_headers():
    settings = _settings(
        email_sender="agent@gmail.com",
        email_app_password="apppass",
        email_recipient="me@gmail.com",
    )
    assert settings.email_enabled is True
    message = build_message("Subject", "Body text", settings)
    assert message["From"] == "agent@gmail.com"
    assert message["To"] == "me@gmail.com"
    assert message["Subject"] == "Subject"
    assert "Body text" in message.get_content()
