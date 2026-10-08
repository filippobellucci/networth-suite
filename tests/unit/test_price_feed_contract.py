"""
Contract tests for price-feed's own talk to Yahoo (`services/price-feed/app/main.py`).

Everything yfinance can hand back is faked at the `yf.Ticker` boundary with
shapes modelled on what Yahoo actually sends, not an idealised response:
a `fast_info` missing a field entirely, a `history()` frame with a NaN
`Close` in the middle of otherwise good rows, a frame still only half full
because the trading day in progress, an empty frame for a ticker Yahoo has
never heard of, a raised exception for a transient failure. No test here
reaches the network -- `yf` itself is stubbed out at import time (as
test_price_cache.py already does), and this file replaces its `Ticker`
per test, so the suite passes with the network disconnected.

Five of these are the bugs `DESIGN_NOTES.md` lists under `price-feed`,
each paid for once already:
  * `_ticker_currency`'s "USD" guess kept forever instead of being
    correctable on the next lookup;
  * `_fetch_price_on_date` caching a day that was still trading as if it
    were the finished close;
  * `_fetch_intraday` doing the same for the hourly series;
  * a NaN `last_price` from `fast_info` shipped as the price instead of
    falling through to the history-based fallback;
  * a NaN `Close` row in a history frame used instead of being dropped.
A sixth test pins the general contract (CLAUDE.md principle 1): a ticker
Yahoo has nothing for, or a request that fails outright, comes back as
"no price", never as a crash or a fabricated number.
"""
from __future__ import annotations

import sys
import types
from dataclasses import dataclass
from datetime import date, datetime

import pytest

pytestmark = pytest.mark.unit

pd = pytest.importorskip("pandas", reason="price-feed's own dependency; see requirements.txt")


@pytest.fixture(scope="module")
def price_feed():
    """Imports price-feed with a placeholder yfinance, same trick as
    test_price_cache.py: nothing here ever calls the real package, so this
    file does not need it installed to be collected -- only pandas, which
    the fixtures below build realistic `history()` frames out of."""
    if "yfinance" not in sys.modules:
        stub = types.ModuleType("yfinance")
        stub.Ticker = lambda *a, **k: None  # noqa: ARG005 - replaced per test
        sys.modules["yfinance"] = stub
    from service_loader import service_module

    return service_module("price_app", "main")


@pytest.fixture(autouse=True)
def _clean_caches(price_feed):
    """Every cache here is a module-level global, so without this a price
    set by one test would be served to the next one -- the exact kind of
    cross-test leak `_ticker_currency`'s "forever" bug would hide behind."""
    price_feed._price_cache.clear()
    price_feed._fx_cache.clear()
    price_feed._historical_cache.clear()
    price_feed._intraday_cache.clear()
    price_feed._currency_cache.clear()


@dataclass
class Recorded:
    """One ticker's recorded Yahoo answers. Mutable on purpose: a test that
    checks "is a stale answer still being served" needs to change what
    Yahoo would say on the *second* call without touching the first."""
    history_frame: object = None
    history_error: Exception | None = None
    fast_info: object = None
    fast_info_error: Exception | None = None


class _FakeTicker:
    def __init__(self, responses: dict[str, Recorded], ticker: str):
        self._responses = responses
        self._ticker = ticker

    @property
    def fast_info(self):
        r = self._responses[self._ticker]
        if r.fast_info_error is not None:
            raise r.fast_info_error
        return r.fast_info

    def history(self, **kwargs):  # noqa: ARG002 - the fixture, not the window, decides the answer
        r = self._responses[self._ticker]
        if r.history_error is not None:
            raise r.history_error
        return r.history_frame


@pytest.fixture
def yahoo(price_feed, monkeypatch) -> dict[str, Recorded]:
    """Replaces price-feed's `yf` with one backed by per-ticker `Recorded`
    answers that the test controls and can change mid-test."""
    responses: dict[str, Recorded] = {}

    class _FakeYf:
        @staticmethod
        def Ticker(ticker):
            return _FakeTicker(responses, ticker)

    monkeypatch.setattr(price_feed, "yf", _FakeYf)
    return responses


@pytest.fixture
def frozen_today(price_feed, monkeypatch):
    """Controls `date.today()` as price-feed sees it. A test that depends
    on which day it runs on is a bomb with a wall-clock fuse."""
    state = {"today": date(2026, 3, 10)}

    class _FrozenDate:
        @staticmethod
        def today():
            return state["today"]

    monkeypatch.setattr(price_feed, "date", _FrozenDate)
    return state


@pytest.fixture
def frozen_clock(price_feed, monkeypatch):
    """Controls `time.time()` as every TtlCache sees it."""
    state = {"now": 1_700_000_000.0}
    monkeypatch.setattr(price_feed.time, "time", lambda: state["now"])
    return state


def _daily_history(rows: list[tuple[date, float]], tz: str = "Europe/Rome"):
    """A `history()` frame shaped like Yahoo's: a tz-aware DatetimeIndex
    (Milan-listed tickers come back in Europe/Rome) and a float `Close`
    column -- the two fields every price-feed function actually reads."""
    if not rows:
        return pd.DataFrame(
            {"Close": pd.Series(dtype="float64")},
            index=pd.DatetimeIndex([], tz=tz),
        )
    idx = pd.DatetimeIndex([pd.Timestamp(d) for d, _ in rows]).tz_localize(tz)
    return pd.DataFrame({"Close": [c for _, c in rows]}, index=idx)


def _intraday_history(day: date, hours_and_closes: list[tuple[int, float]], tz: str = "Europe/Rome"):
    idx = pd.DatetimeIndex(
        [pd.Timestamp(datetime(day.year, day.month, day.day, h)) for h, _ in hours_and_closes]
    ).tz_localize(tz)
    return pd.DataFrame({"Close": [c for _, c in hours_and_closes]}, index=idx)


# --------------------------------------------------------------- the baseline


def test_a_closed_days_close_is_served_and_cached_for_good(price_feed, yahoo, frozen_today):
    ticker = "NORMALCO.MI"
    frozen_today["today"] = date(2026, 3, 10)
    yahoo[ticker] = Recorded(
        history_frame=_daily_history([(date(2026, 3, 6), 50.0), (date(2026, 3, 9), 51.25)]),
        fast_info=types.SimpleNamespace(currency="EUR"),
    )

    payload = price_feed._fetch_price_on_date(ticker, date(2026, 3, 9))

    assert payload == {
        "ticker": ticker,
        "requested_date": "2026-03-09",
        "actual_date": "2026-03-09",
        "price": 51.25,
        "currency": "EUR",
    }
    assert price_feed._historical_cache.get(f"{ticker}|2026-03-09") == payload


# --------------------------------------------- bug: today's bar is not final


def test_todays_partial_bar_is_not_mistaken_for_the_close_once_the_day_is_over(
    price_feed, yahoo, frozen_today
):
    """Yahoo's window query for "today" includes today's own row, still
    moving as the market trades. Caching it under today's date would make
    tomorrow's request for "yesterday" (now a finished day) replay that
    mid-session snapshot forever -- the bug `_fetch_price_on_date`'s
    `actual_date < date.today()` guard exists to prevent."""
    ticker = "PARTIALCO.MI"
    day1 = date(2026, 3, 10)
    frozen_today["today"] = day1
    yahoo[ticker] = Recorded(
        history_frame=_daily_history([(date(2026, 3, 9), 9.5), (day1, 10.0)]),
        fast_info=types.SimpleNamespace(currency="EUR"),
    )

    mid_session = price_feed._fetch_price_on_date(ticker, day1)
    assert mid_session["price"] == 10.0
    assert price_feed._historical_cache.get(f"{ticker}|{day1.isoformat()}") is None, (
        "a day still trading must not be cached as if it were closed"
    )

    # The next day: day1 is over, and Yahoo's record of it now shows the
    # real final close -- different from the mid-session snapshot above.
    frozen_today["today"] = date(2026, 3, 11)
    yahoo[ticker].history_frame = _daily_history([(date(2026, 3, 9), 9.5), (day1, 10.8)])

    final = price_feed._fetch_price_on_date(ticker, day1)
    assert final["price"] == 10.8, "yesterday's close must be re-fetched, not replayed from the cache"


def test_todays_partial_intraday_series_does_not_outlive_the_trading_day(
    price_feed, yahoo, frozen_today, frozen_clock
):
    """Same bug, in `_fetch_intraday`: an intraday series fetched while the
    market is open only holds for the short TTL, so the afternoon can still
    show up once it happens."""
    ticker = "INTRADAYCO.MI"
    today = date(2026, 3, 10)
    frozen_today["today"] = today
    yahoo[ticker] = Recorded(history_frame=_intraday_history(today, [(9, 100.0), (10, 100.5), (11, 101.0)]))

    morning = price_feed._fetch_intraday(ticker, today)
    assert len(morning["points"]) == 3

    frozen_clock["now"] += price_feed.CACHE_TTL_SECONDS + 1
    yahoo[ticker].history_frame = _intraday_history(
        today, [(9, 100.0), (10, 100.5), (11, 101.0), (12, 101.4), (13, 101.1), (14, 100.9), (15, 101.6)]
    )

    afternoon = price_feed._fetch_intraday(ticker, today)
    assert len(afternoon["points"]) == 7, "the afternoon must appear once the short TTL has passed"


# -------------------------------------------------------- bug: NaN is not a price


def test_a_nan_last_price_from_fast_info_falls_back_instead_of_shipping_nan(price_feed, yahoo):
    """`fast_info.last_price` can come back NaN (a known Yahoo data gap).
    Shipped as-is it would crash JSON serialisation; it must fall through
    to the history-based fallback instead."""
    ticker = "NANCO.MI"
    yahoo[ticker] = Recorded(
        fast_info=types.SimpleNamespace(last_price=float("nan"), currency="USD"),
        history_frame=_daily_history([(date(2026, 3, 6), 42.0)]),
    )

    payload = price_feed._fetch_ticker_price(ticker)

    assert payload["price"] == 42.0
    assert payload["currency"] == "USD"


def test_a_nan_close_in_history_is_skipped_not_served(price_feed, yahoo, frozen_today):
    """A NaN `Close` in the middle of a history frame is a Yahoo data gap
    for that one day, not a non-trading day -- it must be dropped so the
    nearest earlier real close is served, not the gap itself."""
    ticker = "GAPCO.MI"
    frozen_today["today"] = date(2026, 3, 10)
    yahoo[ticker] = Recorded(
        history_frame=_daily_history([(date(2026, 3, 6), 50.0), (date(2026, 3, 9), float("nan"))]),
        fast_info=types.SimpleNamespace(currency="EUR"),
    )

    payload = price_feed._fetch_price_on_date(ticker, date(2026, 3, 9))

    assert payload["price"] == 50.0
    assert payload["actual_date"] == "2026-03-06"


# ------------------------------------------------- bug: the currency guess sticks


def test_a_currency_guess_is_corrected_not_kept_forever(price_feed, yahoo, frozen_clock):
    """When Yahoo's lookup fails to report a currency at all, the "USD"
    guess must be kept only briefly, so a later, successful lookup can
    correct it -- not relabel the holding as dollars for good."""
    ticker = "GUESSCO.MI"
    yahoo[ticker] = Recorded(fast_info=types.SimpleNamespace())  # no `currency` field at all

    guess = price_feed._ticker_currency(ticker)
    assert guess == "USD"

    frozen_clock["now"] += price_feed.CACHE_TTL_SECONDS + 1
    yahoo[ticker].fast_info = types.SimpleNamespace(currency="EUR")

    corrected = price_feed._ticker_currency(ticker)
    assert corrected == "EUR", "the guess must not outlive the next successful lookup"


# ---------------------------------------- missing symbol / HTTP failure -> no data


def test_a_yahoo_failure_is_reported_as_missing_not_crashed_or_guessed(price_feed, yahoo, frozen_today):
    """A ticker Yahoo has nothing for comes back as an empty frame; a rate
    limit or a transient 5xx comes back as a raised exception. Either way
    the contract is the same (CLAUDE.md principle 1): no price, surfaced as
    a 404, never a crash and never a fabricated number."""
    frozen_today["today"] = date(2026, 3, 10)

    unknown = "DOESNOTEXIST.MI"
    yahoo[unknown] = Recorded(
        history_frame=_daily_history([]),
        fast_info=types.SimpleNamespace(currency="EUR"),
    )
    assert price_feed._fetch_price_on_date(unknown, date(2026, 3, 9)) is None
    with pytest.raises(price_feed.HTTPException) as exc:
        price_feed.price_on_date(ticker=unknown, date="2026-03-09")
    assert exc.value.status_code == 404

    failing = "RATELIMITED.MI"
    yahoo[failing] = Recorded(
        history_error=Exception(
            "404 Client Error: Not Found for url: "
            "https://query2.finance.yahoo.com/v8/finance/chart/RATELIMITED.MI?..."
        ),
        fast_info=types.SimpleNamespace(currency="EUR"),
    )
    assert price_feed._fetch_price_on_date(failing, date(2026, 3, 9)) is None
    with pytest.raises(price_feed.HTTPException) as exc:
        price_feed.price_on_date(ticker=failing, date="2026-03-09")
    assert exc.value.status_code == 404
