"""
Optional out-of-app alert channel (AGE-11): a plain SMTP email, since the
budget page or bank-sync's status page only get looked at when someone
opens the app. Off by default -- set SMTP_HOST to turn it on -- and never
anything but email: no cloud alerting service, no telemetry, nothing but a
mail server the owner already controls or trusts (see CLAUDE.md principle
3). See DESIGN_NOTES.md for why this channel over the alternatives.

Each caller is responsible for its own "don't repeat the same alert every
cycle" bookkeeping (see core-networth/app/alerts.py and
bank-sync/app/alerts.py) -- this module only ever sends what it's asked to.
"""
import logging
import os
import smtplib
from email.message import EmailMessage

logger = logging.getLogger("notify")

SMTP_HOST = os.environ.get("SMTP_HOST", "")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USERNAME = os.environ.get("SMTP_USERNAME", "")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
SMTP_FROM = os.environ.get("SMTP_FROM", "")
SMTP_TO = os.environ.get("SMTP_TO", "")
SMTP_USE_TLS = os.environ.get("SMTP_USE_TLS", "true").strip().lower() not in ("false", "0", "")


def enabled() -> bool:
    return bool(SMTP_HOST and SMTP_FROM and SMTP_TO)


def send(subject: str, body: str) -> bool:
    """Sends one plain-text email and returns whether it actually went out.
    False, never an exception, both when the channel is off (no SMTP_HOST:
    no connection is even attempted) and when sending itself fails -- a
    misconfigured or unreachable mail server must never take a scheduler
    cycle down with it."""
    if not enabled():
        return False
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = SMTP_FROM
    msg["To"] = SMTP_TO
    msg.set_content(body)
    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=10) as server:
            if SMTP_USE_TLS:
                server.starttls()
            if SMTP_USERNAME:
                server.login(SMTP_USERNAME, SMTP_PASSWORD)
            server.send_message(msg)
        logger.info("Sent alert email: %s", subject)
        return True
    except Exception as e:
        logger.warning("Could not send alert email (%s): %s", subject, e)
        return False
