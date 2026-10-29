"""
The in-memory ledger answers exactly what the per-date queries answered.

Valuing a portfolio on many dates (the history chart, growth, XIRR) used to
run a fresh set of queries per date: 11 seconds and 14,000 queries for two
years of daily expenses. `PortfolioLedger` / `AccountLedger` read the rows
once and answer every date in memory. The rules they implement -- which
balance entry anchors a date, which same-day transactions count after it,
which holding entry is in force -- are delicate, so the queries they replaced
are kept here, verbatim, as the definition, and compared on every day of
randomly generated ledgers, including the cases the API can't produce (rows
with no `created_at`, from before the column existed).
"""
from __future__ import annotations

import random
from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import and_, case, func, or_

pytestmark = pytest.mark.integration

START = date(2025, 1, 1)
DAYS = 120


# ------------------------------------------------- the definitions (pre-ledger queries)
def reference_balance(db, models, account, as_of):
    is_voucher = account.kind == models.CashAccountKind.VOUCHER
    anchor = (
        db.query(models.CashBalanceEntry)
        .filter(models.CashBalanceEntry.account_id == account.id, models.CashBalanceEntry.entry_date <= as_of)
        .order_by(models.CashBalanceEntry.entry_date.desc(), models.CashBalanceEntry.created_at.desc())
        .first()
    )
    raw = anchor.balance if anchor else 0.0
    last_event = anchor.entry_date if anchor else None
    q = db.query(models.CashTransaction).filter(
        models.CashTransaction.account_id == account.id, models.CashTransaction.entry_date <= as_of
    )
    if anchor:
        if anchor.created_at is not None:
            same_day = and_(
                models.CashTransaction.entry_date == anchor.entry_date,
                or_(models.CashTransaction.created_at.is_(None),
                    models.CashTransaction.created_at > anchor.created_at),
            )
        else:
            same_day = models.CashTransaction.entry_date == anchor.entry_date
        q = q.filter(or_(models.CashTransaction.entry_date > anchor.entry_date, same_day))
    delta = func.coalesce(models.CashTransaction.quantity if is_voucher else models.CashTransaction.amount, 0.0)
    signed = case((models.CashTransaction.direction == models.TransactionDirection.INCOME, delta), else_=-delta)
    moved, latest = q.with_entities(func.coalesce(func.sum(signed), 0.0), func.max(models.CashTransaction.entry_date)).one()
    raw += moved
    if latest is not None and (last_event is None or latest > last_event):
        last_event = latest
    return raw, last_event


def reference_holdings(db, models, portfolio_id, as_of):
    entries = (
        db.query(models.HoldingEntry)
        .filter(models.HoldingEntry.portfolio_id == portfolio_id, models.HoldingEntry.entry_date <= as_of)
        .order_by(models.HoldingEntry.asset_id, models.HoldingEntry.entry_date.desc(),
                  models.HoldingEntry.created_at.desc())
        .all()
    )
    latest = {}
    for e in entries:
        latest.setdefault(e.asset_id, e)
    return [e.id for e in latest.values()]


# ------------------------------------------------------------------ random ledgers
# Stands for "no created_at": the column's default would replace a None
# given to the constructor, so these rows are set to NULL after the insert.
_UNKNOWN = datetime(1900, 1, 1)


def _moment(rng, day):
    """A creation time on or around `day` -- or none, a row from before the column."""
    if rng.random() < 0.2:
        return _UNKNOWN
    return datetime.combine(day, datetime.min.time()) + timedelta(minutes=rng.randrange(0, 3 * 24 * 60))


def _build(db, models, seed):
    rng = random.Random(seed)
    p = models.Portfolio(name=f"Random {seed}", base_currency="EUR")
    db.add(p)
    db.flush()
    accounts = []
    for i in range(3):
        voucher = i == 2
        acc = models.CashAccount(portfolio_id=p.id, name=f"A{i}", currency="EUR",
                                 kind=models.CashAccountKind.VOUCHER if voucher else models.CashAccountKind.CURRENCY,
                                 unit_value=7.0 if voucher else None)
        db.add(acc)
        db.flush()
        accounts.append(acc)
        # A few opening balances, often several on one day.
        for _ in range(rng.randrange(0, 8)):
            day = START + timedelta(days=rng.randrange(0, DAYS))
            for _ in range(rng.choice([1, 2, 3])):
                db.add(models.CashBalanceEntry(account_id=acc.id, entry_date=day,
                                               balance=round(rng.uniform(-200, 5000), 2),
                                               created_at=_moment(rng, day)))
        for _ in range(rng.randrange(0, 80)):
            day = START + timedelta(days=rng.randrange(0, DAYS))
            amount = round(rng.uniform(0.01, 400), 2)
            db.add(models.CashTransaction(
                account_id=acc.id, entry_date=day,
                direction=rng.choice([models.TransactionDirection.INCOME, models.TransactionDirection.EXPENSE]),
                amount=amount, quantity=float(rng.randrange(1, 5)) if voucher and rng.random() < 0.9 else None,
                created_at=_moment(rng, day)))
    assets = []
    for i in range(3):
        a = models.Asset(name=f"Asset {seed}-{i}", ticker=None, asset_class=models.AssetClass.OTHER, currency="EUR")
        db.add(a)
        db.flush()
        assets.append(a)
        for _ in range(rng.randrange(0, 10)):
            day = START + timedelta(days=rng.randrange(0, DAYS))
            for _ in range(rng.choice([1, 2])):
                db.add(models.HoldingEntry(portfolio_id=p.id, asset_id=a.id, entry_date=day,
                                           quantity=float(rng.randrange(0, 50)), manual_price=10.0,
                                           created_at=_moment(rng, day)))
    db.flush()
    for model in (models.CashBalanceEntry, models.CashTransaction, models.HoldingEntry):
        db.query(model).filter(model.created_at == _UNKNOWN).update({"created_at": None})
    db.commit()
    db.expire_all()
    return p, accounts


@pytest.mark.parametrize("seed", range(12))
def test_the_ledger_answers_every_day_like_the_per_date_queries(core_modules, db_session, seed):
    models, valuation = core_modules["models"], core_modules["valuation"]
    portfolio, accounts = _build(db_session, models, seed)
    ledger = valuation.PortfolioLedger(db_session, portfolio)

    for offset in range(-3, DAYS + 3):
        day = START + timedelta(days=offset)
        for acc in accounts:
            expected_raw, expected_event = reference_balance(db_session, models, acc, day)
            raw, event = ledger.cash[acc.id].balance(day)
            assert raw == pytest.approx(expected_raw, abs=1e-9), f"seed {seed}, {acc.name}, {day}"
            assert event == expected_event, f"seed {seed}, {acc.name}, {day}"
        assert [e.id for e in ledger.holdings_on(day)] == reference_holdings(db_session, models, portfolio.id, day), \
            f"seed {seed}, holdings on {day}"


def test_the_entry_dates_are_every_date_something_changed(core_modules, db_session):
    models, valuation = core_modules["models"], core_modules["valuation"]
    portfolio, _ = _build(db_session, models, 99)
    expected = set()
    for model, join in ((models.HoldingEntry, None), (models.CashBalanceEntry, models.CashAccount),
                        (models.CashTransaction, models.CashAccount)):
        q = db_session.query(model.entry_date)
        if join is not None:
            q = q.join(join, model.account_id == join.id).filter(join.portfolio_id == portfolio.id)
        else:
            q = q.filter(model.portfolio_id == portfolio.id)
        expected |= {d for (d,) in q.all()}
    assert valuation.PortfolioLedger(db_session, portfolio).entry_dates() == sorted(expected)
