"""Tests for reading/parsing the confirmation reply (no network -- IMAP is faked)."""
from __future__ import annotations

from email.message import EmailMessage

import inbox
import config


# --- parse_selection -----------------------------------------------------------------

def test_parse_affirmative_variants():
    for text in ("apply all", "yes", "Yes please", "confirm", "ok", "approve"):
        assert inbox.parse_selection(text) == "all", text


def test_parse_negative_variants():
    for text in ("no", "No thanks", "cancel", "skip", "stop"):
        assert inbox.parse_selection(text) == "none", text


def test_parse_explicit_numbers_beat_apply_keyword():
    assert inbox.parse_selection("apply 1,3") == {1, 3}
    assert inbox.parse_selection("apply 1-2") == {1, 2}
    assert inbox.parse_selection("2 4") == {2, 4}


def test_parse_unrecognized_is_none():
    assert inbox.parse_selection("") is None
    assert inbox.parse_selection("what does this mean?") is None
    assert inbox.parse_selection(None) is None


def test_strip_quoted_ignores_the_original_below():
    # The quoted proposal lists items "1." and "2." -- they must NOT be read as a selection.
    reply = (
        "apply 1\n"
        "\n"
        "On Sat, Jun 21, 2026 at 9:00 AM Fantasy Bot <bot@gmail.com> wrote:\n"
        "> 1. Set optimal lineup (2 moves)\n"
        "> 2. ADD Reid Detmers / DROP Joe Bench\n"
    )
    assert inbox.parse_selection(reply) == {1}


# --- matches (the security gate) -----------------------------------------------------

def _msg(from_addr: str, subject: str, body: str) -> EmailMessage:
    m = EmailMessage()
    m["From"] = from_addr
    m["Subject"] = subject
    m.set_content(body)
    return m


def test_matches_requires_trusted_sender_and_token():
    token = "a1b2c3d4"
    good = _msg("Me <me@x.com>", f"Re: proposal [FB {token}]", "apply all")
    assert inbox.matches(good, sender="me@x.com", token=token) is True

    wrong_sender = _msg("Stranger <evil@x.com>", f"Re: proposal [FB {token}]", "apply all")
    assert inbox.matches(wrong_sender, sender="me@x.com", token=token) is False

    wrong_token = _msg("me@x.com", "Re: proposal [FB deadbeef]", "apply all")
    assert inbox.matches(wrong_token, sender="me@x.com", token=token) is False


# --- fetch_reply against a fake IMAP -------------------------------------------------

class FakeIMAP:
    """Minimal stand-in for imaplib.IMAP4_SSL used as a context manager."""

    def __init__(self, messages):
        self.messages = messages  # list[(bytes_num, raw_bytes)]
        self.stored: list[tuple] = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def login(self, user, password):
        return ("OK", [b""])

    def select(self, mailbox="INBOX"):
        return ("OK", [b"1"])

    def search(self, charset, *criteria):
        return ("OK", [b" ".join(num for num, _ in self.messages)])

    def fetch(self, num, spec):
        for n, raw in self.messages:
            if n == num:
                return ("OK", [(b"meta", raw)])
        return ("NO", [None])

    def store(self, num, flags, value):
        self.stored.append((num, flags, value))
        return ("OK", [b""])


def _settings(**over) -> config.Settings:
    base = dict(
        league_id=1, year=2026, team_id=1, timezone="UTC", espn_s2="s2", swid="{S}",
        email_sender="bot@gmail.com", email_app_password="pw", email_recipient="me@x.com",
    )
    base.update(over)
    return config.Settings(**base)


def test_fetch_reply_matches_and_marks_seen(monkeypatch):
    token = "a1b2c3d4"
    msg = _msg("me@x.com", f"Re: proposal [FB {token}]", "apply 1,3")
    fake = FakeIMAP([(b"1", msg.as_bytes())])
    monkeypatch.setattr(inbox.imaplib, "IMAP4_SSL", lambda host: fake)

    reply = inbox.fetch_reply(_settings(), token)
    assert reply is not None
    assert reply.selection == {1, 3}
    assert fake.stored and fake.stored[0][2] == "\\Seen"  # marked read


def test_fetch_reply_ignores_wrong_sender(monkeypatch):
    token = "a1b2c3d4"
    msg = _msg("evil@x.com", f"Re: proposal [FB {token}]", "apply all")
    fake = FakeIMAP([(b"1", msg.as_bytes())])
    monkeypatch.setattr(inbox.imaplib, "IMAP4_SSL", lambda host: fake)

    assert inbox.fetch_reply(_settings(), token) is None
    assert fake.stored == []  # untrusted message left UNSEEN


def test_fetch_reply_disabled_without_confirm_config(monkeypatch):
    # No email creds -> confirm disabled -> never touches IMAP.
    def boom(host):
        raise AssertionError("should not connect when confirm is disabled")

    monkeypatch.setattr(inbox.imaplib, "IMAP4_SSL", boom)
    settings = _settings(email_sender=None, email_app_password=None, email_recipient=None)
    assert inbox.fetch_reply(settings, "tok") is None
