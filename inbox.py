"""Read the confirmation reply from the agent Gmail (IMAP) and parse the approval.

The daily proposal email carries a single-use queue token in its subject. To approve, you
reply ``apply all`` / ``apply 1,3`` / ``no``. This module finds that reply and turns it into
a selection the executor can act on.

Two hard security gates (workspace mandate: treat all external input as malicious):
  1. **Sender allow-list** -- the reply's From address must equal ``settings.confirm_address``
     exactly (your own inbox), parsed from the header, not a loose substring.
  2. **Token match** -- the reply must echo the queue's token (Gmail keeps it in the subject
     and quoted body), so a stale "yes" can't apply a newer queue.

Even past those gates, the parsed reply only ever *selects among already-queued transactions*
(see ``pending.py``); it can never describe a new move. The parser is a pure function unit-
tested with hand-built ``email.message`` objects -- no socket.
"""
from __future__ import annotations

import email
import html as html_lib
import imaplib
import re
from dataclasses import dataclass
from email.message import Message
from email.utils import parseaddr

import config
from pending import parse_numbers

# Lines at/after these markers are the quoted original, not the user's reply.
_QUOTE_MARKERS = (
    re.compile(r"^On .*wrote:\s*$"),
    re.compile(r"^-+\s*Original Message\s*-+", re.IGNORECASE),
    re.compile(r"^_{5,}\s*$"),
    re.compile(r"^From:\s", re.IGNORECASE),
)
_NEGATIVE = re.compile(r"\b(no|none|cancel|skip|stop|reject|decline|nope)\b")
_AFFIRM = re.compile(r"\b(yes|yep|all|apply|confirm|confirmed|ok|okay|approve|accept|go)\b")

# HTML tags that end a visual line; each becomes a newline so the reply keeps its structure.
_BLOCK_BREAK = re.compile(r"(?i)<br\s*/?>|</(?:p|div|li|tr|h[1-6]|blockquote)>")
# Opening <blockquote> wraps the quoted original in Gmail/iOS replies. Turning it into a
# ``>``-prefixed line lets _strip_quoted cut the quote even when there's no "On ... wrote:".
_BLOCKQUOTE_OPEN = re.compile(r"(?i)<blockquote[^>]*>")


def _html_to_text(markup: str) -> str:
    """Flatten an HTML email part to line-structured plain text.

    Naively stripping tags (``<[^>]+>`` -> space) collapses the whole message onto one line,
    which defeats quote-stripping and makes ``parse_selection`` read stray numbers out of the
    quoted proposal. So we first turn line-ending tags into newlines and mark the quoted
    ``<blockquote>`` with ``>``, then drop the remaining tags and unescape entities.
    """
    text = _BLOCKQUOTE_OPEN.sub("\n> ", markup)
    text = _BLOCK_BREAK.sub("\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    return html_lib.unescape(text)


@dataclass
class Reply:
    """A matched confirmation reply. ``selection`` is 'all', 'none', a set of ints, or None."""

    selection: str | set[int] | None
    sender: str
    body: str


def _strip_quoted(text: str) -> str:
    """Return only the user's typed reply, dropping the quoted original beneath it."""
    lines: list[str] = []
    for line in text.splitlines():
        if line.lstrip().startswith(">"):
            break
        if any(marker.match(line.strip()) for marker in _QUOTE_MARKERS):
            break
        lines.append(line)
    return "\n".join(lines)


def parse_selection(text: str | None) -> str | set[int] | None:
    """Map a reply's text to a selection: 'all', 'none', a set of item numbers, or None.

    None means "couldn't understand" -- the caller should not act, and may ask the user to
    retry. Order matters: an explicit decline wins, then explicit numbers (``apply 1,3``),
    then a bare affirmation (``yes`` / ``apply all``).
    """
    if not text:
        return None
    body = _strip_quoted(text)
    line = next((ln.strip() for ln in body.splitlines() if ln.strip()), "")
    if not line:
        return None
    low = line.lower()
    if _NEGATIVE.search(low):
        return "none"
    numbers = parse_numbers(low)
    if numbers:
        return numbers
    if _AFFIRM.search(low):
        return "all"
    return None


def _text_body(msg: Message) -> str:
    """Best-effort plain-text body of an email.

    Prefers a ``text/plain`` part. When only HTML is available -- multipart with no plain
    part, or a single ``text/html`` message (some phone clients send these) -- convert it to
    line-structured text via ``_html_to_text`` rather than a flat tag-strip, so the quoted
    original stays separable from the user's typed reply.
    """
    if msg.is_multipart():
        plain = _find_part(msg, "text/plain")
        if plain is not None:
            return plain
        html = _find_part(msg, "text/html")
        return _html_to_text(html) if html else ""
    text = _decode(msg)
    return _html_to_text(text) if msg.get_content_type() == "text/html" else text


def _find_part(msg: Message, content_type: str) -> str | None:
    for part in msg.walk():
        if part.get_content_type() == content_type and "attachment" not in str(
            part.get("Content-Disposition", "")
        ):
            return _decode(part)
    return None


def _decode(part: Message) -> str:
    payload = part.get_payload(decode=True)
    if payload is None:
        return ""
    charset = part.get_content_charset() or "utf-8"
    try:
        return payload.decode(charset, errors="replace")
    except (LookupError, ValueError):
        return payload.decode("utf-8", errors="replace")


def matches(msg: Message, *, sender: str, token: str) -> bool:
    """True if ``msg`` is a confirmation reply for ``token`` from the trusted ``sender``."""
    from_addr = parseaddr(msg.get("From", ""))[1].strip().lower()
    if from_addr != sender.strip().lower():
        return False
    haystack = f"{msg.get('Subject', '')}\n{_text_body(msg)}"
    return token in haystack


def fetch_reply(settings: config.Settings, token: str, *, mark_seen: bool = True) -> Reply | None:
    """Find an unseen reply for ``token`` from the trusted address; None if none yet.

    A matched message is marked ``\\Seen`` so it isn't reprocessed, even when the selection
    is unparseable (the caller decides whether to nudge the user). Returns the first match.
    """
    if not settings.confirm_enabled:
        return None
    sender = settings.confirm_address
    with imaplib.IMAP4_SSL(settings.imap_host) as imap:
        imap.login(settings.email_sender, settings.email_app_password)
        imap.select("INBOX")
        typ, data = imap.search(None, "UNSEEN", "FROM", f'"{sender}"')
        if typ != "OK" or not data or not data[0]:
            return None
        for num in data[0].split():
            typ, msg_data = imap.fetch(num, "(RFC822)")
            if typ != "OK" or not msg_data or not isinstance(msg_data[0], tuple):
                continue
            msg = email.message_from_bytes(msg_data[0][1])
            if not matches(msg, sender=sender, token=token):
                continue  # not ours / wrong sender -- leave it UNSEEN
            if mark_seen:
                imap.store(num, "+FLAGS", "\\Seen")
            body = _text_body(msg)
            return Reply(selection=parse_selection(body), sender=sender, body=body)
    return None
