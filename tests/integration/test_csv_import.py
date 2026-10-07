"""
CSV import of bank statement transactions (GET /transactions/export.csv had
no counterpart for the other direction).

Every bank names and orders its columns differently, so the caller picks
which column is which (`column_mapping`) and which date format the file
uses (`date_format`) -- never guessed, since a day/month swap silently
backdates or future-dates every row and quietly wrecks XIRR and the monthly
reports. Re-importing the same file must not create a second copy of what
it already added: see import_fingerprint on CashTransaction.
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from helpers import make_account, make_portfolio, ok

pytestmark = pytest.mark.integration

TODAY = date.today()


def ago(n: int) -> date:
    return TODAY - timedelta(days=n)


def eu(d: date) -> str:
    """DD/MM/YYYY -- the format most of these tests' files use."""
    return d.strftime("%d/%m/%Y")


MAPPING = {"date": "Date", "amount": "Amount", "description": "Description", "counterparty": "Counterparty"}


@pytest.fixture
async def ctx(api, feed):
    p = await make_portfolio(api)
    acc = await make_account(api, p["id"], name="Revolut")
    return {"p": p["id"], "account": acc["id"]}


def body(csv_content, date_format="%d/%m/%Y", mapping=None, **kw):
    return {
        "csv_content": csv_content,
        "column_mapping": mapping or MAPPING,
        "date_format": date_format,
        **kw,
    }


async def preview(api, account_id, **kw):
    return await ok(await api.post(f"/cash-accounts/{account_id}/transactions/import/preview", json=body(**kw)))


async def commit(api, account_id, idempotency_key=None, **kw):
    headers = {"Idempotency-Key": idempotency_key} if idempotency_key else {}
    return await ok(await api.post(
        f"/cash-accounts/{account_id}/transactions/import", json=body(**kw), headers=headers,
    ))


# ------------------------------------------------------------------ valid file
async def test_a_valid_file_is_previewed_then_imported(api, ctx):
    csv_content = (
        "Date,Amount,Description,Counterparty\n"
        f"{eu(ago(10))},-12.50,Weekly shop,Esselunga\n"
        f"{eu(ago(5))},1500.00,Paycheck,Employer SRL\n"
    )
    prev = await preview(api, ctx["account"], csv_content=csv_content)
    assert prev["total_rows"] == 2 and prev["to_import"] == 2
    assert prev["duplicates"] == 0 and prev["errors"] == 0
    assert all(r["transaction_id"] is None for r in prev["rows"]), "a preview writes nothing"

    done = await commit(api, ctx["account"], csv_content=csv_content)
    assert done["to_import"] == 2
    assert all(r["transaction_id"] for r in done["rows"] if r["status"] == "import")

    rows = await ok(await api.get(f"/cash-accounts/{ctx['account']}/transactions"))
    assert len(rows) == 2
    expense = next(r for r in rows if r["direction"] == "EXPENSE")
    income = next(r for r in rows if r["direction"] == "INCOME")
    assert expense["amount"] == 12.5 and expense["counterparty"] == "Esselunga" and expense["note"] == "Weekly shop"
    assert income["amount"] == 1500.0 and income["counterparty"] == "Employer SRL"


# ------------------------------------------------------------------ dirty rows
async def test_dirty_rows_are_discarded_with_reasons_clean_ones_still_import(api, ctx):
    csv_content = (
        "Date,Amount,Description,Counterparty\n"
        f",-12.50,No date,Nowhere\n"                       # missing date
        f"{eu(ago(3))},not-a-number,Bad amount,Somewhere\n"  # unparseable amount
        f"{eu(ago(2))},0,Zero,Nobody\n"                      # zero amount
        f"{eu(ago(1))},-9.99,Good row,Coop\n"                # the one valid row
    )
    prev = await preview(api, ctx["account"], csv_content=csv_content)
    assert prev["total_rows"] == 4
    assert prev["to_import"] == 1 and prev["errors"] == 3
    reasons = {r["row_number"]: r["reason"] for r in prev["rows"] if r["status"] == "error"}
    assert "date" in reasons[1]
    assert "number" in reasons[2]
    assert "zero" in reasons[3]

    done = await commit(api, ctx["account"], csv_content=csv_content)
    assert done["to_import"] == 1
    rows = await ok(await api.get(f"/cash-accounts/{ctx['account']}/transactions"))
    assert len(rows) == 1 and rows[0]["counterparty"] == "Coop"


async def test_a_blank_trailing_line_is_not_reported_as_a_row(api, ctx):
    csv_content = (
        "Date,Amount,Description,Counterparty\n"
        f"{eu(ago(1))},-9.99,Good row,Coop\n"
        ",,,\n"
    )
    prev = await preview(api, ctx["account"], csv_content=csv_content)
    assert prev["total_rows"] == 1


# -------------------------------------------------------------- date format
async def test_the_date_format_is_never_guessed(api, ctx):
    """05/03 is ambiguous: day-first or month-first disagree on which month
    it is. The same string must parse to two different dates depending only
    on date_format, proving nothing is inferred from the data. A full year
    back keeps it safely in the past regardless of when this test runs."""
    ambiguous = date(TODAY.year - 1, 3, 5)
    csv_content = f"Date,Amount\n{eu(ambiguous)},-5.00\n"

    day_first = await preview(api, ctx["account"], csv_content=csv_content,
                              date_format="%d/%m/%Y", mapping={"date": "Date", "amount": "Amount"})
    month_first = await preview(api, ctx["account"], csv_content=csv_content,
                                date_format="%m/%d/%Y", mapping={"date": "Date", "amount": "Amount"})
    assert day_first["rows"][0]["entry_date"] == ambiguous.isoformat()
    assert month_first["rows"][0]["entry_date"] != day_first["rows"][0]["entry_date"]


async def test_a_date_that_does_not_match_the_given_format_is_an_error_not_a_guess(api, ctx):
    csv_content = f"Date,Amount\n{ago(5).isoformat()},-5.00\n"  # ISO, but format below says DD/MM/YYYY
    prev = await preview(api, ctx["account"], csv_content=csv_content,
                         date_format="%d/%m/%Y", mapping={"date": "Date", "amount": "Amount"})
    assert prev["to_import"] == 0 and prev["errors"] == 1
    assert "doesn't match the format" in prev["rows"][0]["reason"]


# -------------------------------------------------------------------- no doppioni
async def test_reimporting_the_same_file_creates_no_duplicates(api, ctx):
    csv_content = (
        "Date,Amount,Description,Counterparty\n"
        f"{eu(ago(10))},-12.50,Weekly shop,Esselunga\n"
        f"{eu(ago(5))},1500.00,Paycheck,Employer SRL\n"
    )
    first = await commit(api, ctx["account"], csv_content=csv_content)
    assert first["to_import"] == 2 and first["duplicates"] == 0

    second = await commit(api, ctx["account"], csv_content=csv_content)
    assert second["to_import"] == 0 and second["duplicates"] == 2

    rows = await ok(await api.get(f"/cash-accounts/{ctx['account']}/transactions"))
    assert len(rows) == 2, "the second import must not have added anything"


async def test_two_identical_same_day_rows_both_import_once_each(api, ctx):
    """Two genuinely separate vending-machine-style purchases, same date,
    same amount, same (missing) counterparty -- a plain hash of the fields
    can't tell them apart, so both must still be imported once, and
    re-importing the file must recognize both as already present, not just
    one of them."""
    csv_content = (
        "Date,Amount\n"
        f"{eu(ago(4))},-2.50\n"
        f"{eu(ago(4))},-2.50\n"
    )
    mapping = {"date": "Date", "amount": "Amount"}
    first = await commit(api, ctx["account"], csv_content=csv_content, mapping=mapping)
    assert first["to_import"] == 2

    second = await commit(api, ctx["account"], csv_content=csv_content, mapping=mapping)
    assert second["to_import"] == 0 and second["duplicates"] == 2

    rows = await ok(await api.get(f"/cash-accounts/{ctx['account']}/transactions"))
    assert len(rows) == 2


async def test_the_idempotency_key_also_guards_a_retried_commit(api, ctx):
    csv_content = f"Date,Amount\n{eu(ago(1))},-7.00\n"
    mapping = {"date": "Date", "amount": "Amount"}
    first = await commit(api, ctx["account"], csv_content=csv_content, mapping=mapping, idempotency_key="import-1")
    second = await commit(api, ctx["account"], csv_content=csv_content, mapping=mapping, idempotency_key="import-1")
    assert first == second
    rows = await ok(await api.get(f"/cash-accounts/{ctx['account']}/transactions"))
    assert len(rows) == 1


# --------------------------------------------------------------- currency
async def test_a_row_whose_currency_does_not_match_the_account_is_discarded_not_converted(api, ctx):
    csv_content = (
        "Date,Amount,Currency\n"
        f"{eu(ago(3))},-20.00,USD\n"
        f"{eu(ago(2))},-30.00,EUR\n"
    )
    mapping = {"date": "Date", "amount": "Amount", "currency": "Currency"}
    prev = await preview(api, ctx["account"], csv_content=csv_content, mapping=mapping)
    assert prev["to_import"] == 1 and prev["errors"] == 1
    bad = next(r for r in prev["rows"] if r["status"] == "error")
    assert "currency" in bad["reason"] and "USD" in bad["reason"]


# -------------------------------------------------------------- merchant rules
async def test_existing_merchant_rules_apply_to_imported_rows(api, ctx):
    cat = await ok(await api.post("/expense-categories", json={"name": "Groceries"}))
    await ok(await api.post("/merchant-rules", json={"pattern": "Esselunga", "category_id": cat["id"]}))

    csv_content = f"Date,Amount,Counterparty\n{eu(ago(1))},-15.00,Esselunga\n"
    mapping = {"date": "Date", "amount": "Amount", "counterparty": "Counterparty"}
    await commit(api, ctx["account"], csv_content=csv_content, mapping=mapping)

    rows = await ok(await api.get(f"/cash-accounts/{ctx['account']}/transactions"))
    assert rows[0]["category_id"] == cat["id"]


# ------------------------------------------------------------------- guard rails
async def test_an_unmapped_column_name_is_rejected_before_any_row_is_read(api, ctx):
    csv_content = f"Date,Amount\n{eu(ago(1))},-5.00\n"
    resp = await api.post(
        f"/cash-accounts/{ctx['account']}/transactions/import/preview",
        json=body(csv_content=csv_content, mapping={"date": "Date", "amount": "NotAColumn"}),
    )
    assert resp.status_code == 400
    assert "NotAColumn" in resp.text


async def test_a_voucher_account_cannot_import_a_csv(api, ctx):
    voucher = await make_account(api, ctx["p"], name="Meal vouchers", kind="VOUCHER", unit_value=7.0)
    csv_content = f"Date,Amount\n{eu(ago(1))},-7.00\n"
    resp = await api.post(
        f"/cash-accounts/{voucher['id']}/transactions/import/preview",
        json=body(csv_content=csv_content, mapping={"date": "Date", "amount": "Amount"}),
    )
    assert resp.status_code == 400
