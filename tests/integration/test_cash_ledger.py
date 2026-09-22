"""
The cash ledger: balances, the expense/income ledger on top of them,
refunds, transfers and vouchers.

A balance is not a stored field. It is the most recent manually-set entry on
or before the date, plus every transaction after it -- an opening balance
followed by a bank statement. Almost everything below is a consequence of
that, and the edges (a transaction on the same day as the opening balance,
a refund larger than its expense, a transfer between currencies) are where
the bugs were.
"""
from __future__ import annotations

import pytest

from helpers import (add_transaction, cash_balance_of, days_ago, make_account,
                     make_portfolio, ok, set_balance, snapshot, today_iso)

pytestmark = pytest.mark.integration


@pytest.fixture
async def portfolio(api, feed):
    feed.set_fx("USD", "EUR", live=2.0, historical=4.0)
    feed.set_fx("EUR", "USD", live=0.5, historical=0.25)
    return await make_portfolio(api, currency="EUR")


# ------------------------------------------------------------------- balances
async def test_the_opening_balance_is_the_balance(api, portfolio):
    acc = await make_account(api, portfolio["id"])
    await set_balance(api, acc["id"], 1500, on=days_ago(10))
    assert await cash_balance_of(api, portfolio["id"], acc["id"]) == 1500.0


async def test_transactions_move_the_balance_from_there(api, portfolio):
    acc = await make_account(api, portfolio["id"])
    await set_balance(api, acc["id"], 1000, on=days_ago(10))
    await add_transaction(api, acc["id"], "EXPENSE", 250, on=days_ago(5))
    await add_transaction(api, acc["id"], "INCOME", 100, on=days_ago(3))
    assert await cash_balance_of(api, portfolio["id"], acc["id"]) == 850.0


async def test_a_balance_on_a_past_date_ignores_later_movements(api, portfolio):
    acc = await make_account(api, portfolio["id"])
    await set_balance(api, acc["id"], 1000, on=days_ago(10))
    await add_transaction(api, acc["id"], "EXPENSE", 250, on=days_ago(2))
    assert await cash_balance_of(api, portfolio["id"], acc["id"], as_of=days_ago(5)) == 1000.0
    assert await cash_balance_of(api, portfolio["id"], acc["id"]) == 750.0


async def test_a_later_opening_balance_re_anchors_the_account(api, portfolio):
    """Setting the balance by hand again says "it is really this now", which
    has to supersede everything before it."""
    acc = await make_account(api, portfolio["id"])
    await set_balance(api, acc["id"], 1000, on=days_ago(10))
    await add_transaction(api, acc["id"], "EXPENSE", 400, on=days_ago(8))
    await set_balance(api, acc["id"], 5000, on=days_ago(5))
    assert await cash_balance_of(api, portfolio["id"], acc["id"]) == 5000.0


async def test_a_transaction_on_the_opening_balance_s_own_day_still_counts(api, portfolio):
    """The common case -- create the account and log its first movement
    straight away -- and a strict "after the anchor's date" comparison
    silently dropped it."""
    acc = await make_account(api, portfolio["id"])
    await set_balance(api, acc["id"], 1000, on=days_ago(3))
    await add_transaction(api, acc["id"], "EXPENSE", 40, on=days_ago(3))
    assert await cash_balance_of(api, portfolio["id"], acc["id"]) == 960.0


async def test_an_overdraft_is_a_legitimate_balance(api, portfolio):
    acc = await make_account(api, portfolio["id"])
    await set_balance(api, acc["id"], 100, on=days_ago(5))
    await add_transaction(api, acc["id"], "EXPENSE", 500, on=days_ago(1))
    assert await cash_balance_of(api, portfolio["id"], acc["id"]) == -400.0


# ------------------------------------------------------------------- vouchers
async def test_a_voucher_account_counts_units_and_values_them(api, portfolio):
    acc = await make_account(api, portfolio["id"], name="Meal vouchers",
                             kind="VOUCHER", unit_value=7.5)
    await set_balance(api, acc["id"], 40, on=days_ago(5))
    snap = await snapshot(api, portfolio["id"])
    position = snap["cash_positions"][0]
    assert position["balance"] == 40.0, "the balance of a voucher account is a unit count"
    assert position["value_base_ccy"] == 300.0, "40 x 7.50"


async def test_a_voucher_transaction_moves_units_and_freezes_its_money_value(api, portfolio):
    acc = await make_account(api, portfolio["id"], kind="VOUCHER", unit_value=7.5)
    await set_balance(api, acc["id"], 40, on=days_ago(5))
    txn = await add_transaction(api, acc["id"], "EXPENSE", amount=None, quantity=3, on=days_ago(1))
    assert txn["quantity"] == 3
    assert txn["amount"] == pytest.approx(22.5), "3 x 7.50, frozen at the time it was logged"
    assert await cash_balance_of(api, portfolio["id"], acc["id"]) == 37.0


async def test_a_voucher_amount_cannot_be_set_directly(api, portfolio):
    """It would leave the money figure and the unit count permanently
    irreconcilable."""
    acc = await make_account(api, portfolio["id"], kind="VOUCHER", unit_value=7.5)
    await set_balance(api, acc["id"], 40, on=days_ago(5))
    txn = await add_transaction(api, acc["id"], "EXPENSE", amount=None, quantity=2)
    response = await api.patch(f"/cash-transactions/{txn['id']}", json={"amount": 999})
    assert response.status_code == 400


async def test_changing_the_unit_value_leaves_logged_amounts_frozen(api, portfolio):
    acc = await make_account(api, portfolio["id"], kind="VOUCHER", unit_value=7.5)
    await set_balance(api, acc["id"], 40, on=days_ago(5))
    logged = await add_transaction(api, acc["id"], "EXPENSE", amount=None, quantity=2)
    assert logged["amount"] == pytest.approx(15.0), "2 x 7.50 at the time it was logged"
    await ok(await api.patch(f"/cash-accounts/{acc['id']}", json={"unit_value": 9.0}))

    again = await ok(await api.get(f"/cash-accounts/{acc['id']}/transactions"))
    assert again[0]["amount"] == pytest.approx(15.0), "already logged, so it keeps its value"
    snap = await snapshot(api, portfolio["id"])
    assert snap["cash_positions"][0]["value_base_ccy"] == pytest.approx(38 * 9.0)


# -------------------------------------------------------------------- refunds
async def test_a_refund_reduces_the_expense_it_points_at(api, portfolio):
    acc = await make_account(api, portfolio["id"])
    await set_balance(api, acc["id"], 1000, on=days_ago(10))
    expense = await add_transaction(api, acc["id"], "EXPENSE", 200, on=days_ago(5))
    await add_transaction(api, acc["id"], "INCOME", 50, on=days_ago(3),
                          refund_of_id=expense["id"])

    summary = await ok(await api.get("/expenses/summary", params={
        "from_date": days_ago(30), "to_date": today_iso(),
        "portfolio_id": portfolio["id"], "currency": "EUR"}))
    assert summary["total_expense"] == pytest.approx(150.0), "200 spent, 50 came back"
    assert summary["total_income"] == 0.0, "a refund is not income while it is absorbed"
    assert await cash_balance_of(api, portfolio["id"], acc["id"]) == 850.0


async def test_a_refund_larger_than_its_expense_counts_the_excess_as_income(api, portfolio):
    acc = await make_account(api, portfolio["id"])
    await set_balance(api, acc["id"], 1000, on=days_ago(10))
    expense = await add_transaction(api, acc["id"], "EXPENSE", 100, on=days_ago(5))
    await add_transaction(api, acc["id"], "INCOME", 130, on=days_ago(3),
                          refund_of_id=expense["id"])

    summary = await ok(await api.get("/expenses/summary", params={
        "from_date": days_ago(30), "to_date": today_iso(),
        "portfolio_id": portfolio["id"], "currency": "EUR"}))
    assert summary["total_expense"] == 0.0
    assert summary["total_income"] == pytest.approx(30.0)


async def test_only_an_income_can_be_a_refund(api, portfolio):
    acc = await make_account(api, portfolio["id"])
    await set_balance(api, acc["id"], 1000, on=days_ago(10))
    expense = await add_transaction(api, acc["id"], "EXPENSE", 100, on=days_ago(5))
    response = await api.post(f"/cash-accounts/{acc['id']}/transactions", json={
        "entry_date": today_iso(), "direction": "EXPENSE", "amount": 10,
        "refund_of_id": expense["id"]})
    assert response.status_code == 400


async def test_a_refund_cannot_point_at_another_refund(api, portfolio):
    acc = await make_account(api, portfolio["id"])
    await set_balance(api, acc["id"], 1000, on=days_ago(10))
    expense = await add_transaction(api, acc["id"], "EXPENSE", 100, on=days_ago(5))
    refund = await add_transaction(api, acc["id"], "INCOME", 40, on=days_ago(4),
                                   refund_of_id=expense["id"])
    response = await api.post(f"/cash-accounts/{acc['id']}/transactions", json={
        "entry_date": today_iso(), "direction": "INCOME", "amount": 5,
        "refund_of_id": refund["id"]})
    assert response.status_code == 400


async def test_a_refund_must_be_in_the_same_currency(api, portfolio):
    """They are netted one-for-one with no conversion, so crossing currencies
    would silently misstate both."""
    eur = await make_account(api, portfolio["id"], name="EUR", currency="EUR")
    usd = await make_account(api, portfolio["id"], name="USD", currency="USD")
    await set_balance(api, eur["id"], 1000, on=days_ago(10))
    await set_balance(api, usd["id"], 1000, on=days_ago(10))
    expense = await add_transaction(api, eur["id"], "EXPENSE", 100, on=days_ago(5))
    response = await api.post(f"/cash-accounts/{usd['id']}/transactions", json={
        "entry_date": today_iso(), "direction": "INCOME", "amount": 100,
        "refund_of_id": expense["id"]})
    assert response.status_code == 400


async def test_deleting_an_expense_unlinks_its_refunds(api, portfolio):
    """A refund left pointing at a deleted expense counted as neither expense
    nor income while still moving the balance -- money that really came back,
    visible in no report at all."""
    acc = await make_account(api, portfolio["id"])
    await set_balance(api, acc["id"], 1000, on=days_ago(10))
    expense = await add_transaction(api, acc["id"], "EXPENSE", 200, on=days_ago(5))
    refund = await add_transaction(api, acc["id"], "INCOME", 50, on=days_ago(3),
                                   refund_of_id=expense["id"])
    await ok(await api.delete(f"/cash-transactions/{expense['id']}"), 204)

    summary = await ok(await api.get("/expenses/summary", params={
        "from_date": days_ago(30), "to_date": today_iso(),
        "portfolio_id": portfolio["id"], "currency": "EUR"}))
    assert summary["total_income"] == pytest.approx(50.0), "now ordinary income"
    assert summary["total_expense"] == 0.0
    rows = await ok(await api.get(f"/cash-accounts/{acc['id']}/transactions"))
    assert [r for r in rows if r["id"] == refund["id"]][0]["refund_of_id"] is None


async def test_a_refunded_expense_cannot_be_turned_into_an_income(api, portfolio):
    """Flipping it would leave its refunds netted against a row the report no
    longer counts as spending, and their income would silently vanish."""
    acc = await make_account(api, portfolio["id"])
    await set_balance(api, acc["id"], 1000, on=days_ago(10))
    expense = await add_transaction(api, acc["id"], "EXPENSE", 200, on=days_ago(5))
    await add_transaction(api, acc["id"], "INCOME", 50, on=days_ago(3),
                          refund_of_id=expense["id"])
    response = await api.patch(f"/cash-transactions/{expense['id']}", json={"direction": "INCOME"})
    assert response.status_code == 400
    # an unrelated edit is still fine
    await ok(await api.patch(f"/cash-transactions/{expense['id']}", json={"note": "still editable"}))


# ------------------------------------------------------------------ transfers
async def test_a_transfer_moves_money_without_being_spending(api, portfolio):
    a = await make_account(api, portfolio["id"], name="A")
    b = await make_account(api, portfolio["id"], name="B")
    await set_balance(api, a["id"], 1000, on=days_ago(10))
    await set_balance(api, b["id"], 0, on=days_ago(10))

    await ok(await api.post("/transfers", json={
        "from_account_id": a["id"], "to_account_id": b["id"],
        "entry_date": today_iso(), "amount": 250}))

    assert await cash_balance_of(api, portfolio["id"], a["id"]) == 750.0
    assert await cash_balance_of(api, portfolio["id"], b["id"]) == 250.0
    summary = await ok(await api.get("/expenses/summary", params={
        "from_date": days_ago(30), "to_date": today_iso(),
        "portfolio_id": portfolio["id"], "currency": "EUR"}))
    assert summary["total_expense"] == 0.0 and summary["total_income"] == 0.0


async def test_a_cross_currency_transfer_converts_the_receiving_leg(api, portfolio):
    eur = await make_account(api, portfolio["id"], name="EUR", currency="EUR")
    usd = await make_account(api, portfolio["id"], name="USD", currency="USD")
    await set_balance(api, eur["id"], 1000, on=days_ago(10))
    await set_balance(api, usd["id"], 0, on=days_ago(10))

    await ok(await api.post("/transfers", json={
        "from_account_id": eur["id"], "to_account_id": usd["id"],
        "entry_date": today_iso(), "amount": 100}))

    assert await cash_balance_of(api, portfolio["id"], eur["id"]) == 900.0
    assert await cash_balance_of(api, portfolio["id"], usd["id"]) == pytest.approx(50.0)


async def test_a_transfer_to_the_same_account_is_refused(api, portfolio):
    a = await make_account(api, portfolio["id"], name="A")
    await set_balance(api, a["id"], 1000, on=days_ago(10))
    response = await api.post("/transfers", json={
        "from_account_id": a["id"], "to_account_id": a["id"],
        "entry_date": today_iso(), "amount": 10})
    assert response.status_code == 400


async def test_deleting_one_leg_of_a_transfer_removes_both(api, portfolio):
    """Otherwise money appears from nowhere: the source is refunded while the
    destination keeps what it received."""
    a = await make_account(api, portfolio["id"], name="A")
    b = await make_account(api, portfolio["id"], name="B")
    await set_balance(api, a["id"], 1000, on=days_ago(10))
    await set_balance(api, b["id"], 0, on=days_ago(10))
    transfer = await ok(await api.post("/transfers", json={
        "from_account_id": a["id"], "to_account_id": b["id"],
        "entry_date": today_iso(), "amount": 250}))

    await ok(await api.delete(f"/cash-transactions/{transfer['from_leg']['id']}"), 204)
    assert await cash_balance_of(api, portfolio["id"], a["id"]) == 1000.0
    assert await cash_balance_of(api, portfolio["id"], b["id"]) == 0.0


# ------------------------------------------------------------ expense report
async def test_spending_is_broken_down_by_category(api, portfolio):
    acc = await make_account(api, portfolio["id"])
    await set_balance(api, acc["id"], 1000, on=days_ago(10))
    groceries = await ok(await api.post("/expense-categories", json={"name": "Groceries"}))
    await add_transaction(api, acc["id"], "EXPENSE", 60, on=days_ago(4),
                          category_id=groceries["id"])
    await add_transaction(api, acc["id"], "EXPENSE", 40, on=days_ago(3),
                          category_id=groceries["id"])
    await add_transaction(api, acc["id"], "EXPENSE", 25, on=days_ago(2))

    summary = await ok(await api.get("/expenses/summary", params={
        "from_date": days_ago(30), "to_date": today_iso(),
        "portfolio_id": portfolio["id"], "currency": "EUR"}))
    by_name = {row["category_name"]: row["total"] for row in summary["by_category"]}
    assert by_name["Groceries"] == pytest.approx(100.0)
    assert by_name["Uncategorized"] == pytest.approx(25.0)
    assert summary["total_expense"] == pytest.approx(125.0)


async def test_deleting_a_category_keeps_its_transactions(api, portfolio):
    acc = await make_account(api, portfolio["id"])
    await set_balance(api, acc["id"], 1000, on=days_ago(10))
    category = await ok(await api.post("/expense-categories", json={"name": "Temporary"}))
    txn = await add_transaction(api, acc["id"], "EXPENSE", 30, on=days_ago(2),
                                category_id=category["id"])
    await ok(await api.delete(f"/expense-categories/{category['id']}"), 204)

    rows = await ok(await api.get(f"/cash-accounts/{acc['id']}/transactions"))
    kept = [r for r in rows if r["id"] == txn["id"]][0]
    assert kept["category_id"] is None, "the tag goes, the spending stays"
    assert await cash_balance_of(api, portfolio["id"], acc["id"]) == 970.0


async def test_amounts_are_converted_into_the_requested_currency(api, portfolio):
    usd = await make_account(api, portfolio["id"], name="USD", currency="USD")
    await set_balance(api, usd["id"], 1000, on=days_ago(10))
    await add_transaction(api, usd["id"], "EXPENSE", 100, on=days_ago(4))

    summary = await ok(await api.get("/expenses/summary", params={
        "from_date": days_ago(30), "to_date": today_iso(),
        "portfolio_id": portfolio["id"], "currency": "EUR"}))
    assert summary["total_expense"] == pytest.approx(400.0), "100 USD at that day's 4.0"
