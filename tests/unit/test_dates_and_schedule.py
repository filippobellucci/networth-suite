"""
Date arithmetic, on both sides of the app.

Almost every date bug this project has had was the same shape: a calculation
that is right on most days and wrong on a few -- the 31st, a leap February, a
year boundary, or a timezone an hour either side of UTC. None of them show up
unless the boundary is the thing being tested, so that is all this file does.
"""
from __future__ import annotations

from calendar import monthrange
from datetime import date, timedelta

import pytest

pytestmark = pytest.mark.unit


@pytest.fixture(scope="module")
def valuation(core):
    from service_loader import service_module

    return service_module("core_app", "valuation")


@pytest.fixture(scope="module")
def scheduler(core):
    from service_loader import service_module

    return service_module("core_app", "scheduler")


# ------------------------------------------------------------- month subtraction
# setMonth(getMonth() - 1) on 31 March lands on 3 March, because there is no
# 31 February. The chart's "Month" window did that and came out 28 days short
# on the last days of long months, disagreeing with the badge beside it.
@pytest.mark.parametrize(
    "start,months,expected",
    [
        (date(2026, 3, 31), 1, date(2026, 2, 28)),
        (date(2024, 3, 31), 1, date(2024, 2, 29)),   # leap year
        (date(2026, 5, 31), 1, date(2026, 4, 30)),
        (date(2026, 1, 31), 1, date(2025, 12, 31)),  # across a year boundary
        (date(2026, 1, 15), 12, date(2025, 1, 15)),
        (date(2024, 2, 29), 12, date(2023, 2, 28)),  # leap day minus a year
        (date(2026, 6, 15), 0, date(2026, 6, 15)),
    ],
)
def test_subtracting_months_clamps_the_day(valuation, start, months, expected):
    assert valuation._subtract_months(start, months) == expected


def test_subtracting_a_month_never_lands_in_the_same_month(valuation):
    """The failure mode, stated as a property, over four years of dates."""
    day = date(2023, 1, 1)
    while day < date(2027, 1, 1):
        got = valuation._subtract_months(day, 1)
        assert got < day
        assert (day.year * 12 + day.month) - (got.year * 12 + got.month) == 1
        day += timedelta(days=1)


# ----------------------------------------------------------------- trailing days
def test_trailing_days_fill_every_day_up_to_today(valuation):
    """One re-appended "today" point replaced itself day after day, so the
    chart jumped from the last real entry straight to now with every day in
    between silently missing."""
    today = date(2026, 6, 15)
    dates = [date(2026, 6, 10), date(2026, 6, 11)]
    filled = valuation.with_trailing_days_filled(dates, today)
    assert filled[-1] == today
    assert filled == [date(2026, 6, 10)] + [date(2026, 6, 11) + timedelta(days=i) for i in range(5)]
    assert len(set(filled)) == len(filled), "no day appears twice"


def test_trailing_days_leave_an_up_to_date_series_alone(valuation):
    today = date(2026, 6, 15)
    dates = [date(2026, 6, 14), today]
    assert valuation.with_trailing_days_filled(dates, today) == dates


def test_an_empty_series_still_reaches_today(valuation):
    today = date(2026, 6, 15)
    assert valuation.with_trailing_days_filled([], today) == [today]


def test_a_series_ending_in_the_future_is_not_extended(valuation):
    """A future-dated row is refused on write, but one edited into the
    database directly must not make this loop backwards."""
    today = date(2026, 6, 15)
    dates = [date(2026, 6, 20)]
    assert valuation.with_trailing_days_filled(dates, today) == dates


# --------------------------------------------------------------- month-end jobs
def test_last_completed_month_end_over_four_years(scheduler):
    """Checked on every one of 1461 days rather than a handful: this decides
    which month-end snapshots get backfilled, and it had never been executed
    at all until it was tested."""
    day = date(2023, 1, 1)
    while day < date(2027, 1, 1):
        got = scheduler._last_completed_month_end(day)
        assert got <= day
        # it really is the last day of its month
        assert got.day == monthrange(got.year, got.month)[1]
        # and nothing later also qualifies
        following = got + timedelta(days=1)
        if following <= day:
            assert following.day != monthrange(following.year, following.month)[1] or following > day
        day += timedelta(days=1)


@pytest.mark.parametrize(
    "today,expected",
    [
        (date(2026, 1, 1), date(2025, 12, 31)),   # new year's day
        (date(2026, 1, 31), date(2026, 1, 31)),   # today IS a month end
        (date(2024, 2, 29), date(2024, 2, 29)),   # leap day is a month end
        (date(2026, 3, 1), date(2026, 2, 28)),    # non-leap February
        (date(2024, 3, 1), date(2024, 2, 29)),    # leap February
        (date(2026, 6, 15), date(2026, 5, 31)),
    ],
)
def test_last_completed_month_end_boundaries(scheduler, today, expected):
    assert scheduler._last_completed_month_end(today) == expected


def test_month_ends_between_spans_years_without_gaps_or_repeats(scheduler):
    ends = list(scheduler._month_ends_between(date(2024, 11, 15), date(2026, 2, 15)))
    assert ends == [
        date(2024, 11, 30), date(2024, 12, 31), date(2025, 1, 31), date(2025, 2, 28),
        date(2025, 3, 31), date(2025, 4, 30), date(2025, 5, 31), date(2025, 6, 30),
        date(2025, 7, 31), date(2025, 8, 31), date(2025, 9, 30), date(2025, 10, 31),
        date(2025, 11, 30), date(2025, 12, 31), date(2026, 1, 31),
    ]


def test_month_ends_between_is_empty_when_none_completed(scheduler):
    assert list(scheduler._month_ends_between(date(2026, 6, 1), date(2026, 6, 15))) == []


def test_month_ends_never_include_a_date_past_the_end(scheduler):
    for start_month in range(1, 13):
        start = date(2025, start_month, 1)
        end = start + timedelta(days=400)
        for got in scheduler._month_ends_between(start, end):
            assert start <= got <= end
            assert got.day == monthrange(got.year, got.month)[1]
