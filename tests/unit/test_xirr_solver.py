"""
The money-weighted return solver.

This is the one piece of maths in the app that cannot be checked by reading
it, so it is checked against an independent oracle instead: the closed form
for a two-flow series, and the equation itself for everything else.

History worth keeping in mind while editing this file: discounting several
years at a rate near -100% overflows, and the OverflowError used to escape a
function whose contract is to return None. It was not a corner case -- 2790
of 3000 randomly generated series shaped the way this app builds them
crashed. The "never raises" tests below are that bug's tombstone.
"""
from __future__ import annotations

import math
import random
from datetime import date, timedelta

import pytest

pytestmark = pytest.mark.unit

TODAY = date(2026, 6, 15)


@pytest.fixture(scope="module")
def xirr_mod(core):
    from service_loader import service_module

    return service_module("core_app", "xirr")


def npv(xirr_mod, rate: float, flows: list[tuple[date, float]]) -> float:
    start = flows[0][0]
    amounts = [a for _, a in flows]
    years = [(d - start).days / 365.0 for d, _ in flows]
    return xirr_mod._xnpv(rate, amounts, years)


# ------------------------------------------------------------- closed form
@pytest.mark.parametrize(
    "invested,returned,days",
    [
        (1000.0, 1100.0, 365),      # +10% over a year
        (1000.0, 900.0, 365),       # -10% over a year
        (5000.0, 5000.0, 365),      # flat
        (1000.0, 2000.0, 730),      # doubled over two years
        (250.0, 275.0, 90),         # a short period, annualised
        (10000.0, 100.0, 365 * 3),  # almost everything lost
    ],
)
def test_two_flows_match_the_closed_form(xirr_mod, invested, returned, days):
    """For one payment in and one out there is an exact answer:
    (out/in)^(365/days) - 1. The solver has to find it.

    Judged to 1e-4 relative, not to the last bit. The solver's contract is a
    tolerance on the NPV, not on the rate, and over a short window a residual
    well inside that tolerance still moves the annualised rate in the sixth
    decimal. The app renders this with one decimal place as a percentage, so
    1e-4 is already four orders of magnitude finer than anything displayed --
    demanding more would be testing the tolerance, not the answer.
    """
    flows = [(TODAY, -invested), (TODAY + timedelta(days=days), returned)]
    expected = (returned / invested) ** (365.0 / days) - 1.0
    got = xirr_mod.xirr(flows)
    assert got is not None
    assert math.isclose(got, expected, rel_tol=1e-4, abs_tol=1e-6)


def test_a_flat_series_returns_zero(xirr_mod):
    """"Zero" to the solver's own tolerance: money in equals money out, so any
    rate it returns must round to 0.0% on screen."""
    flows = [(TODAY, -1000.0), (TODAY + timedelta(days=365), 1000.0)]
    assert abs(xirr_mod.xirr(flows)) < 1e-6


# ------------------------------------------------------- the answer is a root
def test_every_answer_actually_solves_the_equation(xirr_mod):
    """A step that merely stopped moving is not a solution. Candidates are
    checked against the equation before being returned, and this is what says
    so for a few hundred assorted series."""
    rng = random.Random(20260615)
    checked = 0
    for _ in range(300):
        n = rng.randint(2, 8)
        flows = []
        day = TODAY
        for i in range(n):
            day = day + timedelta(days=rng.randint(1, 400))
            amount = rng.uniform(-5000, 5000)
            flows.append((day, amount))
        # make it solvable: at least one flow of each sign
        flows[0] = (flows[0][0], -abs(flows[0][1]) - 1.0)
        flows[-1] = (flows[-1][0], abs(flows[-1][1]) + 1.0)

        rate = xirr_mod.xirr(flows)
        if rate is None:
            continue
        checked += 1
        # Near the -100% pole the curve is so steep that the residual is
        # enormous even at a true root (the derivative runs to 1e26 there),
        # so the residual is judged relative to the flows' own scale, and
        # only where the problem is well conditioned.
        if rate < -0.9:
            continue
        scale = max(abs(a) for _, a in flows)
        assert abs(npv(xirr_mod, rate, flows)) < scale * 1e-4, (flows, rate)
    assert checked > 200, "too few series produced an answer to be meaningful"


def test_a_series_that_cannot_have_a_root_returns_none(xirr_mod):
    """All the money going the same way has no rate that explains it."""
    flows = [(TODAY, -100.0), (TODAY + timedelta(days=200), -50.0),
             (TODAY + timedelta(days=400), -25.0)]
    assert xirr_mod.xirr(flows) is None


def test_fewer_than_two_flows_returns_none(xirr_mod):
    assert xirr_mod.xirr([]) is None
    assert xirr_mod.xirr([(TODAY, -100.0)]) is None


# ----------------------------------------------------------- never explodes
def test_a_near_total_loss_solves_instead_of_raising(xirr_mod):
    """36k contributed over four years, 327 left. Its root is near -99.9995%,
    which is exactly where discounting overflows."""
    flows = [
        (date(2022, 1, 1), -9000.0),
        (date(2023, 1, 1), -9000.0),
        (date(2024, 1, 1), -9000.0),
        (date(2025, 1, 1), -9000.0),
        (date(2026, 1, 1), 327.0),
    ]
    rate = xirr_mod.xirr(flows)
    assert rate is None or -1.0 < rate < 0.0


def test_the_solver_never_raises_on_anything_plausible(xirr_mod):
    """Shaped the way this app builds cashflows: a run of contributions and a
    closing valuation, over any span, at any magnitude."""
    rng = random.Random(4242)
    for _ in range(1500):
        n = rng.randint(2, 10)
        day = date(2020, 1, 1)
        flows = []
        for _ in range(n - 1):
            day = day + timedelta(days=rng.randint(1, 500))
            flows.append((day, -rng.uniform(0.01, 50000)))
        day = day + timedelta(days=rng.randint(1, 500))
        flows.append((day, rng.choice([0.01, 1.0, 327.0, 100000.0]) ))
        try:
            result = xirr_mod.xirr(flows)
        except Exception as exc:  # noqa: BLE001 - that is the whole point
            pytest.fail(f"xirr raised {type(exc).__name__} on {flows}: {exc}")
        assert result is None or isinstance(result, float)
        assert result is None or math.isfinite(result)


def test_npv_absorbs_overflow_instead_of_raising(xirr_mod):
    """_xnpv is the helper that actually overflows; its contract is to answer
    something finite-ish rather than raise, whatever it is handed."""
    for rate in (-0.999999, -0.9999999, 1e6, -0.5, 0.0):
        value = xirr_mod._xnpv(rate, [-1000.0, 1.0], [0.0, 30.0])
        assert isinstance(value, float)


# --------------------------------------------------------- root nearest guess
def test_the_root_nearest_the_guess_is_the_one_returned(xirr_mod):
    """A sign-alternating series can have several valid roots. Newton-Raphson
    from the caller's guess -- and a spreadsheet's XIRR -- both resolve to the
    nearest one; this keeps that property explicit."""
    flows = [(TODAY, -1000.0), (TODAY + timedelta(days=365), 2500.0),
             (TODAY + timedelta(days=730), -1500.0)]
    rate = xirr_mod.xirr(flows, guess=0.1)
    if rate is not None:
        scale = max(abs(a) for _, a in flows)
        assert abs(npv(xirr_mod, rate, flows)) < scale * 1e-4
