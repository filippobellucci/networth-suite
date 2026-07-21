"""
Read-only diagnostic: prints the exact cashflows the XIRR calculation is
using for a portfolio (or combined across all portfolios), for both the
"1Y" and "All-time" windows, plus which holding/cash account each flow came
from and an independent NPV check at the solved rate.

Does not modify anything. Reuses the app's own xirr.py functions directly
(build_portfolio_cashflows, xirr) so the numbers shown are guaranteed to
match what the running app actually computes -- this is not a reimplementation.

Usage (run inside the core-networth container):
    docker compose exec core-networth python -m app.debug_xirr <portfolio_id>
    docker compose exec core-networth python -m app.debug_xirr combined
    docker compose exec core-networth python -m app.debug_xirr            # lists portfolios
"""
import asyncio
import sys
from datetime import date

from .database import SessionLocal
from . import models, xirr as xirr_mod
from .valuation import distinct_entry_dates, _subtract_months


def _label_for_flow(db, portfolio_id: int, flow_date: date, amount: float) -> str:
    """Best-effort human label for a flow by matching date+portfolio against
    the actual holding/cash entries that would have produced it. Purely for
    readability in this diagnostic; the flow list itself does not depend on
    this function."""
    labels = []

    holdings = (
        db.query(models.HoldingEntry)
        .filter(models.HoldingEntry.portfolio_id == portfolio_id, models.HoldingEntry.entry_date == flow_date)
        .all()
    )
    for h in holdings:
        asset = db.query(models.Asset).filter(models.Asset.id == h.asset_id).first()
        if asset:
            labels.append(f"asset qty-change: {asset.name} ({asset.ticker or 'manual'})")

    accounts = db.query(models.CashAccount).filter(models.CashAccount.portfolio_id == portfolio_id).all()
    for acc in accounts:
        entry = (
            db.query(models.CashBalanceEntry)
            .filter(models.CashBalanceEntry.account_id == acc.id, models.CashBalanceEntry.entry_date == flow_date)
            .first()
        )
        if entry:
            labels.append(f"cash balance-change: {acc.name} [{acc.category}]")

    return " / ".join(labels) if labels else "(portfolio start or end valuation)"


async def dump_for_portfolio(db, portfolio: models.Portfolio):
    today = date.today()
    entry_dates = distinct_entry_dates(db, portfolio.id)
    earliest = entry_dates[0] if entry_dates else today
    year_start = max(_subtract_months(today, 12), earliest)

    print(f"\n{'='*70}")
    print(f"Portfolio: {portfolio.name}  (id={portfolio.id}, base_ccy={portfolio.base_currency})")
    print(f"  earliest tracked entry: {earliest.isoformat()}")
    print(f"  1Y window would start:  {year_start.isoformat()}  "
          f"{'<-- SAME as earliest -> 1Y and All-time will be identical' if year_start == earliest else ''}")
    print(f"{'='*70}")

    for key, start in (("1Y", year_start), ("ALL-TIME", earliest)):
        if start >= today:
            print(f"\n--- {key}: not enough data (start >= today) ---")
            continue

        flows = await xirr_mod.build_portfolio_cashflows(db, portfolio, start)
        print(f"\n--- {key} window (start_date={start.isoformat()}) ---")
        if not flows:
            print("  (no cashflows reconstructed)")
            continue

        for d, amount in sorted(flows, key=lambda f: f[0]):
            label = _label_for_flow(db, portfolio.id, d, amount)
            sign = "OUT (invested)" if amount < 0 else "IN  (value/withdrawal)"
            print(f"  {d.isoformat()}  {sign:>22}  {amount:>14,.2f}  {label}")

        rate = xirr_mod.xirr(flows)
        if rate is None:
            print("  -> XIRR: could not be solved (need 2+ flows with mixed signs)")
        else:
            print(f"  -> XIRR solved rate: {rate*100:+.2f}%/year")
            # Independent verification: recompute NPV at the solved rate directly,
            # separately from xirr.py's own xnpv(), to catch any discrepancy.
            sorted_flows = sorted(flows, key=lambda f: f[0])
            t0 = sorted_flows[0][0]
            npv_check = sum(
                amt / ((1.0 + rate) ** ((d - t0).days / 365.0))
                for d, amt in sorted_flows
            )
            print(f"     independent NPV check at that rate: {npv_check:,.6f}  (should be ~0)")
            span_days = (sorted_flows[-1][0] - sorted_flows[0][0]).days
            print(f"     actual span of these flows: {span_days} days "
                  f"({span_days/365.0:.2f} years) -- short spans amplify the annualized % a lot")


async def main():
    db = SessionLocal()
    try:
        arg = sys.argv[1] if len(sys.argv) > 1 else None

        if arg is None:
            portfolios = db.query(models.Portfolio).filter(models.Portfolio.archived == False).all()  # noqa: E712
            print("Portfolios:")
            for p in portfolios:
                print(f"  id={p.id}  name={p.name!r}  base_ccy={p.base_currency}")
            print("\nRun again with a portfolio id, or 'combined'.")
            return

        if arg == "combined":
            portfolios = db.query(models.Portfolio).filter(models.Portfolio.archived == False).all()  # noqa: E712
            for p in portfolios:
                await dump_for_portfolio(db, p)
            print(f"\n{'='*70}\nNOTE: 'combined' above shows each portfolio separately.")
            print("The app's actual combined XIRR merges all these flows into one series")
            print("(after FX conversion) before solving -- run compute_combined_xirr directly")
            print("if you need the literal merged list.")
        else:
            portfolio = db.query(models.Portfolio).filter(models.Portfolio.id == int(arg)).first()
            if not portfolio:
                print(f"No portfolio with id={arg}")
                return
            await dump_for_portfolio(db, portfolio)
    finally:
        db.close()


if __name__ == "__main__":
    asyncio.run(main())
