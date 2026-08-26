"""
Real (money-weighted) return via XIRR, reconstructed from the periodic
snapshots this app already stores -- there's no explicit transaction ledger
(no "deposited €5,000 on March 3rd"), so contributions/withdrawals are
*inferred* from how quantity/balance changed between consecutive entries,
each priced at its own entry date using the same real historical-price
infrastructure the rest of the app already relies on.

Deliberate scope limit: cash account balance changes are treated as
contributions/withdrawals, same as a change in holding quantity. This means
interest credited to a cash account is indistinguishable from a deposit and
would be (slightly) counted as "money added" rather than "return earned" --
correctly modeling that would need an actual transaction ledger, which this
app doesn't have. For ticker/manual-priced assets there's no such ambiguity:
a quantity change is unambiguously a real contribution or withdrawal.
"""
from datetime import date
from typing import List, Optional, Tuple

from sqlalchemy.orm import Session

from . import models, price_client
from .valuation import compute_portfolio_snapshot, distinct_entry_dates, _subtract_months

CashFlow = Tuple[date, float]


def xirr(cashflows: List[CashFlow], guess: float = 0.1, max_iterations: int = 100, tolerance: float = 1e-6) -> Optional[float]:
    """
    Solves for the annualized rate that makes the net present value of
    `cashflows` zero, via Newton-Raphson. Returns None rather than raising
    when there's no sensible answer (fewer than two flows, all the same
    sign, or the iteration doesn't converge) -- a missing result is a normal
    outcome here (e.g. a position that's never had a real change in value).
    """
    if len(cashflows) < 2:
        return None
    if all(cf >= 0 for _, cf in cashflows) or all(cf <= 0 for _, cf in cashflows):
        return None

    flows = sorted(cashflows, key=lambda cf: cf[0])
    t0 = flows[0][0]
    years = [(d - t0).days / 365.0 for d, _ in flows]
    amounts = [cf for _, cf in flows]

    def xnpv(rate: float) -> float:
        return sum(a / (1.0 + rate) ** y for a, y in zip(amounts, years))

    def xnpv_derivative(rate: float) -> float:
        return sum(-y * a / (1.0 + rate) ** (y + 1) for a, y in zip(amounts, years))

    rate = guess
    for _ in range(max_iterations):
        if rate <= -1.0:
            rate = -0.999999
        npv = xnpv(rate)
        if abs(npv) < tolerance:
            return rate
        deriv = xnpv_derivative(rate)
        if deriv == 0:
            return None
        next_rate = rate - npv / deriv
        if next_rate <= -1.0:
            next_rate = (rate - 1.0) / 2  # dampen instead of diverging past -100%
        if abs(next_rate - rate) < tolerance:
            return next_rate
        rate = next_rate
    return None  # did not converge within max_iterations


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

    if is_historical:
        fx = await price_client.get_fx_rate_on_date(price_ccy, base_ccy, at_date)
    else:
        fx = await price_client.get_fx_rate(price_ccy, base_ccy)
    fx = fx if fx is not None else 1.0
    return price * fx


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
            delta = e.quantity - prev_qty
            if delta:
                price = await _resolve_price(e.asset, e.manual_price, e.entry_date, base_ccy)
                if price is not None:
                    cashflows.append((e.entry_date, -delta * price))
            prev_qty = e.quantity

    accounts = db.query(models.CashAccount).filter(models.CashAccount.portfolio_id == portfolio.id).all()
    for acc in accounts:
        entries = (
            db.query(models.CashBalanceEntry)
            .filter(models.CashBalanceEntry.account_id == acc.id)
            .order_by(models.CashBalanceEntry.entry_date, models.CashBalanceEntry.created_at)
            .all()
        )
        prev_balance = 0.0
        for e in entries:
            if e.entry_date <= start_date:
                prev_balance = e.balance
                continue
            delta = e.balance - prev_balance
            if delta:
                is_historical = e.entry_date < today
                if is_historical:
                    fx = await price_client.get_fx_rate_on_date(acc.currency, base_ccy, e.entry_date)
                else:
                    fx = await price_client.get_fx_rate(acc.currency, base_ccy)
                fx = fx if fx is not None else 1.0
                cashflows.append((e.entry_date, -delta * fx))
            prev_balance = e.balance

    end_snapshot = await compute_portfolio_snapshot(db, portfolio, today)
    if end_snapshot.net_worth_base_ccy or cashflows:
        cashflows.append((today, end_snapshot.net_worth_base_ccy))

    return cashflows


async def compute_portfolio_xirr(db: Session, portfolio: models.Portfolio) -> dict:
    """Annualized real return for "the last year" and "since inception", each
    as a percentage (e.g. 8.4 for +8.4%/year), or null if there isn't enough
    data yet to compute a meaningful rate."""
    today = date.today()
    entry_dates = distinct_entry_dates(db, portfolio.id)
    earliest = entry_dates[0] if entry_dates else today
    year_start = max(_subtract_months(today, 12), earliest)

    result = {}
    for key, start in (("year", year_start), ("max", earliest)):
        if start >= today:
            result[key] = None
            continue
        flows = await build_portfolio_cashflows(db, portfolio, start)
        rate = xirr(flows)
        result[key] = (
            {"start_date": start.isoformat(), "rate_pct": round(rate * 100, 2)} if rate is not None else None
        )
    return result


async def compute_combined_xirr(db: Session, base_currency: str = "EUR") -> dict:
    """Same as compute_portfolio_xirr, blended across every portfolio (each
    portfolio's cashflows converted to `base_currency` at each flow's own
    date before combining, so multi-currency portfolios are handled
    consistently with the rest of the app)."""
    today = date.today()
    portfolios = db.query(models.Portfolio).filter(models.Portfolio.archived == False).all()  # noqa: E712
    entry_dates = distinct_entry_dates(db)
    earliest = entry_dates[0] if entry_dates else today
    year_start = max(_subtract_months(today, 12), earliest)

    result = {}
    for key, start in (("year", year_start), ("max", earliest)):
        if start >= today:
            result[key] = None
            continue
        combined_flows: List[CashFlow] = []
        for p in portfolios:
            flows = await build_portfolio_cashflows(db, p, start)
            if p.base_currency == base_currency:
                combined_flows.extend(flows)
                continue
            for d, amount in flows:
                is_historical = d < today
                if is_historical:
                    fx = await price_client.get_fx_rate_on_date(p.base_currency, base_currency, d)
                else:
                    fx = await price_client.get_fx_rate(p.base_currency, base_currency)
                fx = fx if fx is not None else 1.0
                combined_flows.append((d, amount * fx))

        rate = xirr(combined_flows)
        result[key] = (
            {"start_date": start.isoformat(), "rate_pct": round(rate * 100, 2)} if rate is not None else None
        )
    return result
