"""
Recurring-payment detection on its own (core-networth's reports.detect_recurring):
which spending patterns count as a subscription, and which merely look regular.
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from service_loader import service_module

pytestmark = pytest.mark.unit

TODAY = date(2026, 10, 2)


@pytest.fixture(scope="module")
def reports(core):
    """Loaded through the `core` fixture, which points DATA_DIR at a temp
    folder first: importing core-networth creates it, and the default (/data)
    is only writable as root."""
    return service_module("core_app", "reports")


def payments(key, dates_amounts, category=None):
    return [(key, key.title(), d, a, category) for d, a in dates_amounts]


def monthly(n, amount, last=TODAY - timedelta(days=3), drift=0):
    return [(last - timedelta(days=30 * i + (drift if i % 2 else 0)), amount) for i in range(n)][::-1]


def test_a_steady_monthly_charge_is_a_subscription(reports):
    (found,) = reports.detect_recurring(payments("spotify", monthly(5, 10.99)), TODAY)
    assert found["cadence"] == "MONTHLY" and found["active"] and found["price_change"] is None
    assert found["monthly_cost"] == pytest.approx(10.99, abs=0.2)
    assert found["next_expected"] == TODAY - timedelta(days=3) + timedelta(days=30)


def test_billing_dates_that_drift_a_few_days_still_count(reports):
    assert reports.detect_recurring(payments("gym", monthly(5, 30, drift=4)), TODAY)


def test_two_payments_are_not_yet_a_monthly_pattern(reports):
    assert reports.detect_recurring(payments("x", monthly(2, 10)), TODAY) == []


def test_a_yearly_renewal_needs_only_two(reports):
    rows = payments("domain", [(TODAY - timedelta(days=400), 12.0), (TODAY - timedelta(days=35), 12.0)])
    (found,) = reports.detect_recurring(rows, TODAY)
    assert found["cadence"] == "YEARLY" and found["monthly_cost"] == pytest.approx(1.0, abs=0.01)


def test_irregular_dates_are_not_recurring(reports):
    rows = payments("shop", [(TODAY - timedelta(days=d), 20) for d in (3, 11, 40, 47, 90)])
    assert reports.detect_recurring(rows, TODAY) == []


def test_amounts_varying_too_much_are_not_a_subscription(reports):
    rows = payments("market", [(d, a) for (d, _), a in zip(monthly(4, 0), [20, 55, 31, 80])])
    assert reports.detect_recurring(rows, TODAY) == []


def test_a_charge_split_in_two_on_one_day_counts_once(reports):
    dates = monthly(4, 10)
    rows = payments("cloud", dates[:-1] + [(dates[-1][0], 4), (dates[-1][0], 6)])
    (found,) = reports.detect_recurring(rows, TODAY)
    assert found["occurrences"] == 4 and found["last_amount"] == 10


def test_a_tiny_rounding_difference_is_not_a_price_change(reports):
    dates = monthly(4, 9.99)
    rows = payments("phone", dates[:-1] + [(dates[-1][0], 10.00)])
    assert reports.detect_recurring(rows, TODAY)[0]["price_change"] is None


def test_rows_without_a_merchant_are_ignored(reports):
    assert reports.detect_recurring(payments("", monthly(5, 10)), TODAY) == []
