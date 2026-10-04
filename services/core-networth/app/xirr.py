"""
Real (money-weighted) return via XIRR, reconstructed from the periodic
snapshots this app already stores. For holdings there's no explicit
transaction ledger (no "bought 10 shares on March 3rd"), so contributions/
withdrawals are *inferred* from how quantity changed between consecutive
entries, each priced at its own entry date using the same real
historical-price infrastructure the rest of the app already relies on. For
cash accounts, a real transaction ledger (CashTransaction) does exist
alongside manual balance entries -- both are treated as real events here via
`resolve_cash_balance`, the same function used everywhere else a cash
balance is displayed, so this can't drift out of sync with what's shown
elsewhere.

Deliberate scope limit: for cash accounts, a plain balance entry (not backed
by a logged transaction) is still treated as a contribution/withdrawal --
there's no ledger row to tell the two apart, so interest credited by simply
editing the balance by hand is indistinguishable from a deposit. A
CashTransaction logged with `investment_income_kind` set (a dividend, coupon
or interest payment) avoids this: `build_portfolio_cashflows` excludes it
from the delta, so it reads as return instead of as money added -- see
InvestmentIncomeKind in models.py. For ticker/manual-priced assets there's no
such ambiguity: a quantity change is unambiguously a real contribution or
withdrawal.

Pension Fund accounts (AllocationCategory.PENSION_FUND) are the one
exception to "a cash account's balance change is a contribution/withdrawal":
they're treated as a genuine investment instead, like a stock holding --
their balance moves mainly because the fund itself performed well or badly,
not because money was freely added or withdrawn (they don't even accept
Transactions -- see main.py), so no interim cashflow is generated for them
at all. Their value is still fully counted in the start/end snapshot totals;
the difference between those is simply read as return, the same way a
stock's price appreciation is never itself a cashflow.
"""
from datetime import date
from typing import Awaitable, Callable, List, Optional, Tuple

from sqlalchemy.orm import Session

from . import models, price_client
from .valuation import compute_portfolio_snapshot, distinct_entry_dates, resolve_cash_balance, _subtract_months

CashFlow = Tuple[date, float]


# How far below -100%/yr a rate is allowed to go. A portfolio that loses
# nearly everything really does solve down here, so the floor sits below the
# answers; it exists only because 1 + rate must stay strictly positive.
# _xnpv absorbs the under/overflow that discounting at such a rate produces.
_MIN_RATE = -0.999999


def _xnpv(rate: float, amounts: List[float], years: List[float]) -> float:
    """
    Net present value of the flows at `rate`, never raising.

    Discounting over several years at a rate near -100% raises a number close
    to zero to a large power, which under/overflows -- for a portfolio that
    lost nearly all its value. When one term runs off the end of the float
    range it is larger
    than everything else put together by hundreds of orders of magnitude, so
    its sign alone decides the sign of the sum, which is all any caller here
    needs from this function.
    """
    total = 0.0
    for a, y in zip(amounts, years):
        try:
            total += a / (1.0 + rate) ** y
        except (OverflowError, ZeroDivisionError):
            return float("inf") if a > 0 else float("-inf")
    return total


def _solve_by_bisection(
    amounts: List[float], years: List[float], tolerance: float, prefer_near: float
) -> Optional[float]:
    """
    Finds rates where the NPV changes sign and halves each interval down onto
    the root inside it. Slower than Newton-Raphson but it cannot diverge and
    needs no derivative, so it is what answers the cases Newton walks off the
    edge of.

    A cashflow series that changes sign more than once can genuinely have
    several solutions, and none of them is "the" return -- so the one nearest
    `prefer_near` (the caller's guess) is returned, which is both what
    Newton-Raphson would have converged to from that starting point and what
    a spreadsheet's XIRR does with its own guess.
    """
    # Closely spaced near -100%, where a heavy-loss series puts its roots (and
    # can put two of them inside one coarse step, which cancels the sign
    # change that makes them findable at all), and coarse further out, where
    # the curve is smooth.
    ladder = [
        _MIN_RATE, -0.99999, -0.9999, -0.999, -0.995, -0.99, -0.98, -0.95, -0.9, -0.85, -0.75, -0.6,
        -0.5, -0.35, -0.25, -0.1, 0.0, 0.1, 0.25, 0.5, 1.0, 3.0, 10.0, 100.0, 1e4,
    ]
    values = [_xnpv(r, amounts, years) for r in ladder]

    roots = []
    for i in range(len(ladder) - 1):
        lo, hi, f_lo, f_hi = ladder[i], ladder[i + 1], values[i], values[i + 1]
        if f_lo == 0.0:
            roots.append(lo)
            continue
        if (f_lo > 0) == (f_hi > 0):
            continue
        for _ in range(200):
            mid = (lo + hi) / 2
            f_mid = _xnpv(mid, amounts, years)
            if abs(f_mid) < tolerance or hi - lo < 1e-12:
                break
            if (f_lo > 0) != (f_mid > 0):
                hi = mid
            else:
                lo, f_lo = mid, f_mid
        roots.append((lo + hi) / 2)

    if not roots:
        return None
    return min(roots, key=lambda r: abs(r - prefer_near))


def xirr(cashflows: List[CashFlow], guess: float = 0.1, max_iterations: int = 100, tolerance: float = 1e-6) -> Optional[float]:
    """
    Solves for the annualized rate that makes the net present value of
    `cashflows` zero. Returns None rather than raising when there's no
    sensible answer (fewer than two flows, all the same sign, or no rate
    solves them) -- a missing result is a normal outcome here (e.g. a
    position that's never had a real change in value).

    Newton-Raphson first, since it converges in a handful of steps on
    ordinary data, then bisection for anything it cannot land: a rate it
    steps past -100%, a derivative of zero, or a step so small it stops
    moving while the NPV is still far from zero. Every candidate is checked
    against the equation before being handed back.
    """
    if len(cashflows) < 2:
        return None
    if all(cf >= 0 for _, cf in cashflows) or all(cf <= 0 for _, cf in cashflows):
        return None

    flows = sorted(cashflows, key=lambda cf: cf[0])
    t0 = flows[0][0]
    years = [(d - t0).days / 365.0 for d, _ in flows]
    amounts = [cf for _, cf in flows]

    # What counts as "close enough to zero" has to scale with the money
    # involved: 1e-6 is unreachably strict on a portfolio worth millions, and
    # Newton-Raphson's own stopping rule is a step size, not an NPV, so it
    # routinely lands a fraction of a cent away on a six-figure portfolio.
    # A millionth of the money moved is comfortably inside rounding noise
    # while still rejecting an answer that is simply not a solution.
    scale = sum(abs(a) for a in amounts)
    npv_tolerance = max(tolerance, scale * 1e-6)

    def solves(rate: Optional[float]) -> bool:
        return rate is not None and abs(_xnpv(rate, amounts, years)) < npv_tolerance

    rate = guess
    for _ in range(max_iterations):
        if rate <= _MIN_RATE:
            break
        npv = _xnpv(rate, amounts, years)
        if abs(npv) < npv_tolerance:
            return rate
        try:
            deriv = sum(-y * a / (1.0 + rate) ** (y + 1) for a, y in zip(amounts, years))
        except (OverflowError, ZeroDivisionError):
            break
        if deriv == 0:
            break
        next_rate = rate - npv / deriv
        if next_rate <= _MIN_RATE:
            # Creep toward the floor rather than leaping past it: a near-total
            # loss really does solve at a rate down in the -90s.
            next_rate = (rate + _MIN_RATE) / 2
        if abs(next_rate - rate) < tolerance:
            rate = next_rate
            break
        rate = next_rate

    if solves(rate):
        return rate
    return _solve_by_bisection(amounts, years, npv_tolerance, guess)


async def _resolve_price(asset: models.Asset, manual_price: Optional[float], at_date: date, base_ccy: str) -> Optional[float]:
    """Price of one unit of `asset`, in `base_ccy`, on `at_date` -- reuses the
    same historical/live/manual resolution rules as the rest of the app."""
    is_historical = at_date < date.today()

    if manual_price is not None:
        price, price_ccy = manual_price, asset.currency
    elif asset.ticker:
        if is_historical:
            hist = await price_client.get_price_on_date(asset.ticker, at_date)
        else:
            hist = await price_client.get_latest_price(asset.ticker)
        if not hist:
            return None
        price, price_ccy = hist["price"], hist.get("currency", asset.currency)
    else:
        return None

    return price * await price_client.fx_rate_at(price_ccy, base_ccy, at_date)


async def build_portfolio_cashflows(db: Session, portfolio: models.Portfolio, start_date: date) -> List[CashFlow]:
    """
    Reconstructs the dated cashflows for one portfolio from `start_date`
    through today: an initial outflow equal to whatever the portfolio was
    already worth at `start_date` (zero if nothing existed yet), one flow per
    real quantity/balance change after that date, and a final inflow equal to
    today's value. Passing the portfolio's actual earliest tracked date as
    `start_date` gives the all-time ("Max") cashflow series for free, since
    the start valuation is then naturally zero and every change is captured
    by the per-entry deltas -- no special-casing needed between "since a
    past date" and "since inception".
    """
    base_ccy = portfolio.base_currency
    today = date.today()
    cashflows: List[CashFlow] = []

    start_snapshot = await compute_portfolio_snapshot(db, portfolio, start_date)
    if start_snapshot.net_worth_base_ccy:
        cashflows.append((start_date, -start_snapshot.net_worth_base_ccy))

    asset_ids = {
        h.asset_id
        for h in db.query(models.HoldingEntry.asset_id).filter(models.HoldingEntry.portfolio_id == portfolio.id).distinct()
    }
    for asset_id in asset_ids:
        entries = (
            db.query(models.HoldingEntry)
            .filter(models.HoldingEntry.portfolio_id == portfolio.id, models.HoldingEntry.asset_id == asset_id)
            .order_by(models.HoldingEntry.entry_date, models.HoldingEntry.created_at)
            .all()
        )
        prev_qty = 0.0
        for e in entries:
            if e.entry_date <= start_date:
                prev_qty = e.quantity
                continue
            if e.entry_date > today:
                break  # never past the closing valuation -- see event_dates below
            delta = e.quantity - prev_qty
            if delta:
                price = await _resolve_price(e.asset, e.manual_price, e.entry_date, base_ccy)
                if price is not None:
                    cashflows.append((e.entry_date, -delta * price))
            prev_qty = e.quantity

    accounts = db.query(models.CashAccount).filter(models.CashAccount.portfolio_id == portfolio.id).all()
    for acc in accounts:
        if acc.category == models.AllocationCategory.PENSION_FUND:
            # Treated as an investment (see the module docstring): no interim
            # cashflow, so the change between the start/end snapshot totals
            # is read as return.
            continue

        # An archived account (see CashAccount.archived_at) stops counting
        # towards net worth from its archive date on -- mirrored here as a
        # value of 0 from that date, so its last balance shows up as a
        # withdrawal at the close date, matching the end-of-window total.
        close_date = acc.archived_at.date() if acc.archived_at is not None else None

        # A VOUCHER account's balance is a COUNT of units, not money (see
        # resolve_cash_balance): converted, so these cashflows are in the same
        # unit as the start/end snapshot totals they are solved against.
        unit_value = acc.unit_value if acc.kind == models.CashAccountKind.VOUCHER else None

        def value_on(d: date) -> float:
            if close_date is not None and d >= close_date:
                return 0.0
            raw, _ = resolve_cash_balance(db, acc, d)
            return raw * (unit_value or 0.0) if unit_value is not None else raw

        # Every date this account's balance could have changed (a balance
        # entry or a transaction), valued with resolve_cash_balance -- the
        # same function every displayed balance uses.
        event_dates = {
            e.entry_date
            for e in db.query(models.CashBalanceEntry.entry_date).filter(models.CashBalanceEntry.account_id == acc.id)
        } | {
            t.entry_date
            for t in db.query(models.CashTransaction.entry_date).filter(models.CashTransaction.account_id == acc.id)
        }
        if close_date is not None:
            event_dates.add(close_date)
        # Bounded by today as well as by start_date: a flow dated after the
        # closing valuation appended below would make the solved rate
        # meaningless. Writes can't produce a future date
        # (schemas._reject_future_date); a hand-edited row could.
        event_dates = sorted(d for d in event_dates if start_date < d <= today)

        # A dividend/coupon/interest payment (InvestmentIncomeKind) is
        # capital income, not money moved in from outside -- subtracted from
        # the delta below so it reads as return instead of as a
        # contribution. The balance increase it caused is still fully
        # captured by the end snapshot appended after this loop.
        income_by_date: dict[date, float] = {}
        for t in db.query(models.CashTransaction).filter(
            models.CashTransaction.account_id == acc.id,
            models.CashTransaction.investment_income_kind.isnot(None),
            models.CashTransaction.entry_date > start_date,
            models.CashTransaction.entry_date <= today,
        ):
            income_by_date[t.entry_date] = income_by_date.get(t.entry_date, 0.0) + t.amount

        prev_value = value_on(start_date)
        for d in event_dates:
            new_value = value_on(d)
            delta = new_value - prev_value - income_by_date.get(d, 0.0)
            if delta:
                cashflows.append((d, -delta * await price_client.fx_rate_at(acc.currency, base_ccy, d)))
            prev_value = new_value

    end_snapshot = await compute_portfolio_snapshot(db, portfolio, today)
    if end_snapshot.net_worth_base_ccy or cashflows:
        cashflows.append((today, end_snapshot.net_worth_base_ccy))

    return cashflows


async def _xirr_by_window(
    db: Session, portfolio_id: Optional[str], flows_since: Callable[[date], Awaitable[List[CashFlow]]]
) -> dict:
    """Annualized real return for "the last year" and "since inception", each
    as a percentage (e.g. 8.4 for +8.4%/year), or null if there isn't enough
    data yet to compute a meaningful rate. `flows_since(start)` builds the
    cashflows for the window starting at `start`."""
    today = date.today()
    entry_dates = distinct_entry_dates(db, portfolio_id)
    earliest = entry_dates[0] if entry_dates else today
    year_start = max(_subtract_months(today, 12), earliest)

    result = {}
    for key, start in (("year", year_start), ("max", earliest)):
        if start >= today:
            result[key] = None
            continue
        rate = xirr(await flows_since(start))
        result[key] = (
            {"start_date": start.isoformat(), "rate_pct": round(rate * 100, 2)} if rate is not None else None
        )
    return result


async def compute_portfolio_xirr(db: Session, portfolio: models.Portfolio) -> dict:
    """See _xirr_by_window."""
    return await _xirr_by_window(db, portfolio.id, lambda start: build_portfolio_cashflows(db, portfolio, start))


async def compute_combined_xirr(db: Session, base_currency: str = "EUR") -> dict:
    """Same as compute_portfolio_xirr, blended across every portfolio (each
    portfolio's cashflows converted to `base_currency` at each flow's own
    date before combining, so multi-currency portfolios are handled
    consistently with the rest of the app)."""
    portfolios = db.query(models.Portfolio).filter(models.Portfolio.archived == False).all()  # noqa: E712

    async def combined_flows(start: date) -> List[CashFlow]:
        combined: List[CashFlow] = []
        for p in portfolios:
            flows = await build_portfolio_cashflows(db, p, start)
            if p.base_currency == base_currency:
                combined.extend(flows)
                continue
            for d, amount in flows:
                combined.append((d, amount * await price_client.fx_rate_at(p.base_currency, base_currency, d)))
        return combined

    return await _xirr_by_window(db, None, combined_flows)
