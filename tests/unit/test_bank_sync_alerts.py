"""
Out-of-app alerts for bank-sync (AGE-11): a consent about to expire and a
sync that keeps failing already show on the status page, but only to
someone who opens it. These two checks in app/alerts.py send the same
warnings by email instead, each once per problem.

The SMTP channel itself (off unless SMTP_HOST is set) is covered in
tests/unit/test_notify.py; this only covers the dedup bookkeeping -- sent
once, not every cycle, not before the margin/streak is actually reached --
and that the message carries no balance or account number.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from service_loader import service_module

pytestmark = pytest.mark.unit

alerts = service_module("bank_app", "alerts")
models = service_module("bank_app", "models")
database = service_module("bank_app", "database")


@pytest.fixture
def db(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path}/bank_sync.db")
    database.Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine, autoflush=False)()
    yield session
    session.close()


@pytest.fixture
def sent(monkeypatch):
    messages: list[tuple[str, str]] = []
    monkeypatch.setattr(alerts.notify, "send", lambda subject, body: messages.append((subject, body)) or True)
    return messages


def make_link(db, **kw) -> "models.BankLink":
    defaults = dict(
        label="Revolut", aspsp_name="Revolut", aspsp_country="IT",
        portfolio_id="p1", cash_account_id="acc1", status=models.LinkStatus.ACTIVE,
    )
    link = models.BankLink(**{**defaults, **kw})
    db.add(link)
    db.commit()
    return link


# --------------------------------------------------------- consent expiry
def test_a_consent_expiring_within_the_margin_alerts_once(db, sent):
    link = make_link(db, valid_until=datetime.utcnow() + timedelta(days=3))
    alerts.check_consent_expiry(db)
    alerts.check_consent_expiry(db)
    assert len(sent) == 1
    assert "Revolut" in sent[0][1]


def test_a_consent_far_from_expiring_does_not_alert(db, sent):
    make_link(db, valid_until=datetime.utcnow() + timedelta(days=30))
    alerts.check_consent_expiry(db)
    assert sent == []


def test_an_already_expired_consent_does_not_get_the_expiring_soon_alert(db, sent):
    """That's a different, already-visible state (status flips to EXPIRED
    elsewhere, see sync.py) -- this check is only for the advance warning."""
    make_link(db, valid_until=datetime.utcnow() - timedelta(days=1))
    alerts.check_consent_expiry(db)
    assert sent == []


def test_a_renewed_consent_can_alert_again_later(db, sent):
    link = make_link(db, valid_until=datetime.utcnow() + timedelta(days=3))
    alerts.check_consent_expiry(db)
    assert len(sent) == 1

    # Re-authorized: a fresh, later valid_until differs from what was
    # warned about, so it is treated as unwarned-about again.
    link.valid_until = datetime.utcnow() + timedelta(days=95)
    db.commit()
    alerts.check_consent_expiry(db)
    assert len(sent) == 1  # not due yet

    link.valid_until = datetime.utcnow() + timedelta(days=2)
    db.commit()
    alerts.check_consent_expiry(db)
    assert len(sent) == 2


def test_the_consent_alert_carries_no_account_identifier(db, sent):
    make_link(db, valid_until=datetime.utcnow() + timedelta(days=3), cash_account_id="acc-secret-123")
    alerts.check_consent_expiry(db)
    (_, body) = sent[0]
    assert "acc-secret-123" not in body


# ----------------------------------------------------------- sync failures
def test_a_repeating_failure_alerts_once_after_the_streak(db, sent):
    link = make_link(db)
    for _ in range(alerts.SYNC_FAILURE_ALERT_STREAK - 1):
        alerts.note_sync_result(link, failed=True)
        assert sent == []
    alerts.note_sync_result(link, failed=True)
    assert len(sent) == 1

    alerts.note_sync_result(link, failed=True)
    alerts.note_sync_result(link, failed=True)
    assert len(sent) == 1  # still just the once


def test_a_single_bad_cycle_does_not_alert(db, sent):
    link = make_link(db)
    alerts.note_sync_result(link, failed=True)
    assert sent == []


def test_a_recovered_link_can_alert_again_on_a_fresh_streak(db, sent):
    link = make_link(db)
    for _ in range(alerts.SYNC_FAILURE_ALERT_STREAK):
        alerts.note_sync_result(link, failed=True)
    assert len(sent) == 1

    alerts.note_sync_result(link, failed=False)  # a cycle finally succeeds
    assert link.sync_failure_streak == 0
    assert link.sync_error_alerted is False

    for _ in range(alerts.SYNC_FAILURE_ALERT_STREAK):
        alerts.note_sync_result(link, failed=True)
    assert len(sent) == 2
