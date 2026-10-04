"""
build_portfolio_cashflows reconstructs contributions/withdrawals from how a
cash account's balance changed. A dividend, coupon or interest payment is
not money moved in from outside, but before InvestmentIncomeKind existed
there was no way to say so: logging it as a plain income transaction (the
only option) was read as a deposit, which lowers the solved XIRR instead of
raising it -- see DESIGN_NOTES.md and the module docstring in app/xirr.py.
"""
from __future__ import annotations

import pytest

from helpers import add_transaction, days_ago, make_account, make_portfolio, ok, set_balance

pytestmark = pytest.mark.integration


async def _xirr_max_pct(api, portfolio_id):
    body = await ok(await api.get(f"/portfolios/{portfolio_id}/xirr"))
    return body["max"]["rate_pct"]


async def test_a_dividend_raises_xirr_instead_of_lowering_it(api, feed):
    """
    Same facts in both portfolios -- 1000 opening, +50 credited 200 days
    later, 1050 today, tracked over exactly 365 days -- told to XIRR two
    different ways:

    * logged as a plain income, the +50 is read as a deposit, so investing
      1050 total to end up with 1050 is ~0%/year;
    * logged with investment_income_kind="INTEREST", the +50 is excluded
      from the contribution and instead counts fully as return: investing
      1000 to end up with 1050 over exactly one year is exactly 5.00%/year.
    """
    start = days_ago(365)
    mid = days_ago(200)

    plain = await make_portfolio(api, name="Plain income")
    plain_acc = await make_account(api, plain["id"])
    await set_balance(api, plain_acc["id"], 1000, on=start)
    await add_transaction(api, plain_acc["id"], "INCOME", 50, on=mid)

    dividend = await make_portfolio(api, name="Dividend income")
    dividend_acc = await make_account(api, dividend["id"])
    await set_balance(api, dividend_acc["id"], 1000, on=start)
    await add_transaction(api, dividend_acc["id"], "INCOME", 50, on=mid,
                          investment_income_kind="INTEREST")

    plain_rate = await _xirr_max_pct(api, plain["id"])
    dividend_rate = await _xirr_max_pct(api, dividend["id"])

    assert plain_rate == pytest.approx(0.0, abs=0.01), "unflagged, the credit is still counted as money added"
    assert dividend_rate == pytest.approx(5.0, abs=0.01), "flagged, the same credit reads as a 5.00%/year return"
    assert dividend_rate - plain_rate == pytest.approx(5.0, abs=0.01), (
        "the fix is worth exactly the return that was being hidden as a contribution"
    )


async def test_a_dividend_does_not_change_the_balance_or_past_history(api, feed):
    """The fix only changes how XIRR reads the credit -- the account balance,
    and so every past day's valuation, is identical either way (CLAUDE.md
    principle 2: the past is never rewritten by today's choice of label)."""
    from helpers import cash_balance_of

    acc_portfolio = await make_portfolio(api)
    acc = await make_account(api, acc_portfolio["id"])
    await set_balance(api, acc["id"], 1000, on=days_ago(30))
    await add_transaction(api, acc["id"], "INCOME", 50, on=days_ago(10),
                          investment_income_kind="DIVIDEND")

    assert await cash_balance_of(api, acc_portfolio["id"], acc["id"], as_of=days_ago(15)) == 1000.0
    assert await cash_balance_of(api, acc_portfolio["id"], acc["id"]) == 1050.0
