"""Email notifications via the dedicated agent Gmail account (SMTP).

The dedicated co-manager Gmail sends the daily summary to your inbox. Auth uses a Gmail
*App Password* (not the normal password), stored in .env. If email isn't configured the
functions no-op so the job still runs.
"""
from __future__ import annotations

import smtplib
from email.message import EmailMessage

import config

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587


def build_message(
    subject: str, body: str, settings: config.Settings, *, html: str | None = None
) -> EmailMessage:
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = settings.email_sender
    message["To"] = settings.email_recipient
    message.set_content(body)                       # plain-text part (the fallback)
    if html:
        # Adds an HTML alternative; clients prefer the last/most-capable part on a phone,
        # while text-only clients (and the reply parser) still get clean plain text.
        message.add_alternative(html, subtype="html")
    return message


def send_email(
    subject: str, body: str, settings: config.Settings, *, html: str | None = None
) -> bool:
    """Send one email. Returns False (no-op) if email isn't configured."""
    if not settings.email_enabled:
        return False
    message = build_message(subject, body, settings, html=html)
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as smtp:
        smtp.starttls()
        smtp.login(settings.email_sender, settings.email_app_password)
        smtp.send_message(message)
    return True
