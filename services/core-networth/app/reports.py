"""
Reporting over the income/expense ledger: the flows every report is built
from, plus the monthly breakdown, budget progress and recurring-payment
detection built on them.

Every report counts money the same way /expenses/summary always has, which
is why they share `flows` instead of each re-deriving it:

  * transfers between your own accounts are neither income nor spending, and
    are left out entirely;
  * a refunded expense counts at what's left of it after its refunds, and a
    refund only counts as income for whatever exceeded its expense (see
    main.compute_refund_adjustments);
  * each amount is converted into the report's currency at its own day's FX
    rate, falling back to 1:1 when no rate is available -- the long-standing
    behaviour of the summary, kept identical here.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Callable, Optional

from sqlalchemy.orm import Session

from . import models, price_client


@dataclass
class Flow:
    txn: models.CashTransaction
    income: bool
    amount: float  # converted, after refunds; always > 0

    @property
    def month(self) -> str:
        return self.txn.entry_date.strftime("%Y-%m")


async def flows(
    db: Session,
    from_date: date,
    to_date: date,
    portfolio_id: Optional[str],
    currency: str,
    refund_adjustments: tuple[dict[str, float], dict[str, float]],
) -> list[Flow]:
    effective_amounts, excess_amounts = refund_adjustments
    q = db.query(models.CashTransaction).filter(
        models.CashTransaction.entry_date >= from_date,
        models.CashTransaction.entry_date <= to_date,
        models.CashTransaction.transfer_id.is_(None),
    )
    if portfolio_id:
        q = q.join(models.CashAccount, models.CashTransaction.account_id == models.CashAccount.id).filter(
            models.CashAccount.portfolio_id == portfolio_id
        )
    out: list[Flow] = []
    for t in q.all():
        acc = db.get(models.CashAccount, t.account_id)
        fx = await price_client.get_fx_rate_on_date(acc.currency, currency, t.entry_date)
        fx = fx if fx is not None else 1.0
        if t.direction == models.TransactionDirection.INCOME:
            if t.refund_of_id is not None:
                raw = excess_amounts.get(t.id, 0.0)
                if raw <= 0:
                    continue  # fully absorbed by the expense it refunds
            else:
                raw = t.amount
            out.append(Flow(t, True, raw * fx))
        else:
            raw = effective_amounts.get(t.id, t.amount)
            if raw <= 0:
                continue  # fully refunded
            out.append(Flow(t, False, raw * fx))
    return out


def by_category(flows_: list[Flow], income: bool, name_of: Callable[[Optional[str]], str]) -> list[dict]:
    totals: dict[Optional[str], float] = {}
    for f in flows_:
        if f.income == income:
            totals[f.txn.category_id] = totals.get(f.txn.category_id, 0.0) + f.amount
    return [
        {"category_id": cid, "category_name": name_of(cid), "total": total}
        for cid, total in sorted(totals.items(), key=lambda kv: kv[1], reverse=True)
        if total > 0
    ]


# ---------------------------------------------------------------- months
def month_start(d: date) -> date:
    return d.replace(day=1)


def add_months(d: date, n: int) -> date:
    y, m = divmod(d.month - 1 + n, 12)
    return date(d.year + y, m + 1, 1)


def month_end(d: date) -> date:
    return add_months(month_start(d), 1) - timedelta(days=1)


def monthly(flows_: list[Flow], first_month: date, last_month: date) -> list[dict]:
    """One row per calendar month from first_month to last_month inclusive,
    months without a single transaction included as zeros -- a gap in a
    chart would read as missing data rather than a quiet month."""
    rows: dict[str, dict] = {}
    m = month_start(first_month)
    while m <= last_month:
        key = m.strftime("%Y-%m")
        rows[key] = {"month": key, "income": 0.0, "expense": 0.0}
        m = add_months(m, 1)
    for f in flows_:
        row = rows.get(f.month)
        if row is not None:
            row["income" if f.income else "expense"] += f.amount
    for row in rows.values():
        row["income"] = round(row["income"], 2)
        row["expense"] = round(row["expense"], 2)
        row["net"] = round(row["income"] - row["expense"], 2)
        # Share of the month's income that wasn't spent. Undefined without
        # income -- a month of only spending isn't "-infinity percent saved".
        row["savings_rate"] = round(row["net"] / row["income"] * 100, 1) if row["income"] > 0 else None
    return list(rows.values())


# ---------------------------------------------------------------- recurring
# (label, typical days between payments, how far off a single gap may be)
CADENCES = [
    ("WEEKLY", 7, 2),
    ("MONTHLY", 30.44, 6),
    ("QUARTERLY", 91.3, 12),
    ("YEARLY", 365.25, 20),
]
MIN_OCCURRENCES = {"WEEKLY": 4, "MONTHLY": 3, "QUARTERLY": 3, "YEARLY": 2}


def _cadence(gaps: list[int]) -> Optional[tuple[str, float]]:
    """The cadence most gaps agree with: at least 75% of them within its
    tolerance. None when the dates don't follow any of them."""
    if not gaps:
        return None
    for label, days, tolerance in CADENCES:
        regular = sum(1 for g in gaps if abs(g - days) <= tolerance)
        if regular / len(gaps) >= 0.75:
            return label, days
    return None


def detect_recurring(
    expenses: list[tuple[str, str, date, float, Optional[str]]], today: date
) -> list[dict]:
    """
    Recurring payments among `expenses` -- (merchant key, display name, date,
    amount, category_id) rows -- grouped by merchant.

    A merchant is recurring when its payments follow a weekly, monthly,
    quarterly or yearly rhythm (see _cadence) and their amounts stay within
    ±25% of the typical one: a supermarket visited every week is regular in
    time but not in amount, and isn't a subscription. A small price change
    is still the same subscription -- and is reported, because a subscription
    quietly getting more expensive is exactly what this view is for. Several
    payments on one day count once (a split charge isn't two cycles).
    """
    by_key: dict[str, list[tuple[date, float, str, Optional[str]]]] = {}
    for key, name, d, amount, category_id in expenses:
        if key:
            by_key.setdefault(key, []).append((d, amount, name, category_id))

    found = []
    for key, rows in by_key.items():
        per_day: dict[date, float] = {}
        for d, amount, _, _ in rows:
            per_day[d] = per_day.get(d, 0.0) + amount
        dates = sorted(per_day)
        amounts = [per_day[d] for d in dates]
        gaps = [(b - a).days for a, b in zip(dates, dates[1:])]
        cadence = _cadence(gaps)
        if cadence is None:
            continue
        label, period = cadence
        if len(dates) < MIN_OCCURRENCES[label]:
            continue
        typical = statistics.median(amounts)
        if typical <= 0 or any(abs(a - typical) > 0.25 * typical for a in amounts):
            continue

        last_date, last_amount = dates[-1], amounts[-1]
        previous = amounts[-2]
        price_change = None
        if abs(last_amount - previous) >= 0.01 and abs(last_amount - previous) / previous >= 0.02:
            price_change = {"previous": round(previous, 2), "current": round(last_amount, 2), "date": last_date}
        latest = max(rows, key=lambda r: r[0])
        found.append({
            "key": key,
            "name": latest[2],
            "category_id": latest[3],
            "cadence": label,
            "occurrences": len(dates),
            "first_date": dates[0],
            "last_date": last_date,
            "next_expected": last_date + timedelta(days=round(period)),
            "last_amount": round(last_amount, 2),
            "typical_amount": round(typical, 2),
            "monthly_cost": round(last_amount * 30.44 / period, 2),
            # Still going: the next payment isn't overdue by more than half a
            # cycle (a cancelled subscription simply stops appearing).
            "active": (today - last_date).days <= period * 1.5,
            "price_change": price_change,
        })
    found.sort(key=lambda r: (not r["active"], -r["monthly_cost"]))
    return found
