"""
price-feed's cache.

Three separate bugs lived in this one class's semantics:

  * a day's intraday series cached while the market was still trading was
    served as the finished day from the next day on, so the afternoon never
    appeared at all;
  * a currency guessed as "USD" because one lookup was rate-limited was kept
    forever, permanently relabelling a EUR holding as dollars;
  * five caches each repeated the same timestamp/expiry dance with slightly
    different shapes, which is how the first two managed to differ.

So what is tested here is the distinction the class exists to make: an entry
that can never change versus one that is still moving, and who decides which.
"""
from __future__ import annotations

import sys
import types

import pytest

pytestmark = pytest.mark.unit


@pytest.fixture(scope="module")
def price_feed():
    """Imports price-feed with a placeholder yfinance.

    Nothing is called on it at import time -- the module only needs the name
    to bind -- and stubbing it keeps this file free of pandas and numpy, so
    the unit suite stays a sub-second pre-commit check.
    """
    if "yfinance" not in sys.modules:
        stub = types.ModuleType("yfinance")
        stub.Ticker = lambda *a, **k: None  # noqa: ARG005 - never called here
        sys.modules["yfinance"] = stub
    from service_loader import service_module

    return service_module("price_app", "main")


def test_an_entry_is_served_while_it_is_young(price_feed):
    cache = price_feed.TtlCache(ttl=60)
    cache.set("k", {"price": 1.0})
    assert cache.get("k") == {"price": 1.0}


def test_an_entry_is_dropped_once_it_is_older_than_its_ttl(price_feed, monkeypatch):
    clock = {"now": 1000.0}
    monkeypatch.setattr(price_feed.time, "time", lambda: clock["now"])
    cache = price_feed.TtlCache(ttl=60)
    cache.set("k", "v")
    clock["now"] += 59
    assert cache.get("k") == "v"
    clock["now"] += 2
    assert cache.get("k") is None


def test_a_missing_key_is_none(price_feed):
    assert price_feed.TtlCache(ttl=60).get("nothing") is None


def test_forever_really_means_forever(price_feed, monkeypatch):
    """A completed trading day's close and a ticker's quotation currency
    cannot change, so they are kept for the life of the process."""
    clock = {"now": 1000.0}
    monkeypatch.setattr(price_feed.time, "time", lambda: clock["now"])
    cache = price_feed.TtlCache(ttl=price_feed.FOREVER)
    cache.set("2020-01-02", 123.45)
    clock["now"] += 60 * 60 * 24 * 365 * 10
    assert cache.get("2020-01-02") == 123.45


def test_one_entry_can_override_the_cache_default(price_feed, monkeypatch):
    """The decision belongs at write time: the reader cannot tell a finished
    day's data from a snapshot of a day still in progress."""
    clock = {"now": 1000.0}
    monkeypatch.setattr(price_feed.time, "time", lambda: clock["now"])
    cache = price_feed.TtlCache(ttl=price_feed.FOREVER)
    cache.set("a-past-day", "final")
    cache.set("today", "still-moving", ttl=30)
    clock["now"] += 31
    assert cache.get("a-past-day") == "final"
    assert cache.get("today") is None, "today's partial series must not outlive the day"


def test_clearing_empties_everything(price_feed):
    cache = price_feed.TtlCache(ttl=price_feed.FOREVER)
    cache.set("a", 1)
    cache.set("b", 2)
    cache.clear()
    assert cache.get("a") is None and cache.get("b") is None


def test_the_caches_that_must_be_permanent_are(price_feed):
    """Which cache is permanent is a correctness decision, not a tuning one:
    a past day's close and a ticker's currency cannot change, a live price
    can."""
    assert price_feed._historical_cache._ttl == price_feed.FOREVER
    assert price_feed._currency_cache._ttl == price_feed.FOREVER
    assert price_feed._intraday_cache._ttl == price_feed.FOREVER
    assert price_feed._price_cache._ttl != price_feed.FOREVER
    assert price_feed._fx_cache._ttl != price_feed.FOREVER
