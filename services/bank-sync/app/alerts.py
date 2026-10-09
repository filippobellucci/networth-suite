"""
Out-of-app alerts (AGE-11): the status page already warns about a consent
expiring soon and a sync that keeps failing, but only to someone who opens
it. These two checks send the same warnings by email -- see
shared/notify.py for the channel itself (off unless SMTP_HOST is set) and
DESIGN_NOTES.md for why email and why these two conditions.

Neither message carries a balance, an account number or any other
financial figure -- only the bank link's label and, for the sync failure,
how many cycles it has failed -- since an email passes through machines
that aren't the owner's own.
"""
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from . import models
from shared import notify

# Same margin as the in-app warning (README.md "Day to day"): enough notice
# to re-authorize without rushing, never on the day itself.
CONSENT_WARNING_DAYS = 7

# Consecutive failed sync cycles before a problem counts as "repeating"
# rather than one bad cycle -- sync.py already retries a failed cycle on
# its own, so this is for when that retrying itself keeps failing.
SYNC_FAILURE_ALERT_STREAK = 3


def check_consent_expiry(db: Session) -> None:
    now = datetime.utcnow()
    horizon = now + timedelta(days=CONSENT_WARNING_DAYS)
    links = db.query(models.BankLink).filter(models.BankLink.status == models.LinkStatus.ACTIVE).all()
    for link in links:
        if not link.valid_until or not (now < link.valid_until <= horizon):
            continue
        if link.consent_warned_until == link.valid_until:
            continue
        days_left = (link.valid_until - now).days
        sent = notify.send(
            "Net Worth Suite: bank consent expiring soon",
            f'The bank link "{link.label}" needs to be re-authorized within {days_left} day(s), '
            "or automatic capture for it will stop. Open its status page to renew.",
        )
        if sent:
            link.consent_warned_until = link.valid_until
    db.commit()


def note_sync_result(link: "models.BankLink", failed: bool) -> None:
    """Called once per link after every sync attempt, success or failure --
    updates the link's streak but does not commit; the caller already
    commits `link`'s other fields in the same transaction."""
    if not failed:
        link.sync_failure_streak = 0
        link.sync_error_alerted = False
        return
    link.sync_failure_streak = (link.sync_failure_streak or 0) + 1
    if link.sync_failure_streak < SYNC_FAILURE_ALERT_STREAK or link.sync_error_alerted:
        return
    sent = notify.send(
        "Net Worth Suite: bank sync keeps failing",
        f'The bank link "{link.label}" has failed to sync for {link.sync_failure_streak} '
        "cycles in a row. Check its status page or the container log for details.",
    )
    if sent:
        link.sync_error_alerted = True
