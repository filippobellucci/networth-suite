"""
The validators in core-networth's schemas.

Each of these refusals exists because something got through once and cost
more than a rejected request would have. The comments name what.
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

pytestmark = pytest.mark.unit


@pytest.fixture(scope="module")
def schemas(core):
    from service_loader import service_module

    return service_module("core_app", "schemas")


# --------------------------------------------------------------- finite money
# An amount of Infinity was accepted, stored, and from then on every figure it
# fed was infinite too -- which JSON cannot represent, so the dashboard's
# headline endpoint answered 500 and kept answering 500, and the row could not
# be deleted from a UI whose pages were broken by that same value.
@pytest.mark.parametrize("bad", [float("inf"), float("-inf"), float("nan")])
def test_transaction_amount_must_be_a_real_number(schemas, bad):
    with pytest.raises(ValueError):
        schemas.CashTransactionCreate(entry_date=date.today(), direction="EXPENSE", amount=bad)


@pytest.mark.parametrize("bad", [float("inf"), float("-inf"), float("nan")])
def test_balance_must_be_a_real_number(schemas, bad):
    with pytest.raises(ValueError):
        schemas.CashBalanceEntryCreate(entry_date=date.today(), balance=bad)


@pytest.mark.parametrize("bad", [float("inf"), float("-inf"), float("nan")])
def test_holding_quantity_must_be_a_real_number(schemas, bad):
    with pytest.raises(ValueError):
        schemas.HoldingEntryCreate(asset_id="a", entry_date=date.today(), quantity=bad)


@pytest.mark.parametrize("bad", [float("inf"), float("nan")])
def test_manual_price_must_be_a_real_number(schemas, bad):
    with pytest.raises(ValueError):
        schemas.HoldingEntryCreate(asset_id="a", entry_date=date.today(), quantity=1, manual_price=bad)


def test_a_negative_balance_is_still_allowed(schemas):
    """An overdraft is a real balance -- only non-finite values are refused."""
    assert schemas.CashBalanceEntryCreate(entry_date=date.today(), balance=-250.5).balance == -250.5


# ------------------------------------------------------------ positive amounts
@pytest.mark.parametrize("bad", [0, -1, -0.0001])
def test_amounts_must_be_positive(schemas, bad):
    with pytest.raises(ValueError):
        schemas.CashTransactionCreate(entry_date=date.today(), direction="EXPENSE", amount=bad)


def test_transfer_amount_uses_the_same_rule_as_a_transaction(schemas):
    """TransferCreate used to reimplement this and reject with wording that
    named a field transfers do not have."""
    with pytest.raises(ValueError) as exc:
        schemas.TransferCreate(from_account_id="a", to_account_id="b",
                               entry_date=date.today(), amount=0)
    assert "must be positive" in str(exc.value)


# ------------------------------------------------------------------- rounding
def test_money_is_rounded_to_three_decimals(schemas):
    entry = schemas.CashBalanceEntryCreate(entry_date=date.today(), balance=1.23456789)
    assert entry.balance == 1.235


def test_unit_values_keep_four_decimals(schemas):
    """One more than money: a unit value multiplied by a large quantity
    accumulates visible drift at three."""
    acc = schemas.CashAccountCreate(name="V", currency="EUR", kind="VOUCHER", unit_value=7.123456)
    assert acc.unit_value == 7.1235


# ------------------------------------------------------------------ null-ness
# Every *Update schema types its fields Optional so omitting one means "leave
# it alone", but the endpoints apply the payload with exclude_unset=True, which
# KEEPS a field the client sent explicitly as null -- so a NOT NULL column got
# None and the request died at commit time with a 500.
@pytest.mark.parametrize(
    "model_name,field",
    [
        ("PortfolioUpdate", "name"), ("PortfolioUpdate", "base_currency"), ("PortfolioUpdate", "archived"),
        ("AssetUpdate", "name"), ("AssetUpdate", "asset_class"), ("AssetUpdate", "currency"),
        ("HoldingEntryUpdate", "entry_date"), ("HoldingEntryUpdate", "quantity"),
        ("CashAccountUpdate", "name"), ("CashAccountUpdate", "currency"),
        ("CashTransactionUpdate", "entry_date"), ("CashTransactionUpdate", "direction"),
        ("CashTransactionUpdate", "amount"),
        ("ExpenseCategoryUpdate", "name"),
    ],
)
def test_not_null_columns_refuse_an_explicit_null(schemas, model_name, field):
    with pytest.raises(ValueError):
        getattr(schemas, model_name)(**{field: None})


@pytest.mark.parametrize(
    "model_name,field",
    [
        ("PortfolioUpdate", "notes"), ("AssetUpdate", "ticker"), ("AssetUpdate", "isin"),
        ("AssetUpdate", "category"), ("AssetUpdate", "notes"),
        ("HoldingEntryUpdate", "manual_price"), ("CashAccountUpdate", "institution"),
        ("CashAccountUpdate", "unit_value"), ("CashTransactionUpdate", "category_id"),
        ("CashTransactionUpdate", "note"), ("CashTransactionUpdate", "refund_of_id"),
    ],
)
def test_nullable_columns_can_still_be_cleared(schemas, model_name, field):
    """Clearing a ticker, un-categorising a transaction, un-linking a refund:
    all real edits, and all must survive the rule above."""
    model = getattr(schemas, model_name)(**{field: None})
    assert field in model.model_dump(exclude_unset=True)
    assert getattr(model, field) is None


def test_omitting_a_field_still_means_unchanged(schemas):
    model = schemas.PortfolioUpdate(notes="only this")
    assert model.model_dump(exclude_unset=True) == {"notes": "only this"}


# ------------------------------------------------------------------- currency
# A malformed currency code reaches Intl.NumberFormat in the browser, which
# throws on anything that isn't three letters -- and an unhandled throw there
# used to blank the whole page, including the button needed to fix the value.
@pytest.mark.parametrize("bad", ["", "E", "EU", "EURO", "12A", "E U", "€€€"])
def test_currency_must_be_three_letters(schemas, bad):
    with pytest.raises(ValueError):
        schemas.PortfolioCreate(name="P", base_currency=bad)


def test_currency_is_upper_cased(schemas):
    assert schemas.PortfolioCreate(name="P", base_currency=" eur ").base_currency == "EUR"


# ----------------------------------------------------------------- entry dates
# A future-dated entry sorts after the closing valuation XIRR solves against
# (turning a healthy account into a -98%/year return) and puts a point past
# today on the chart with the days between never filled in.
def test_a_far_future_date_is_refused(schemas):
    with pytest.raises(ValueError):
        schemas.CashBalanceEntryCreate(entry_date=date.today() + timedelta(days=2), balance=1)


def test_tomorrow_is_read_as_today(schemas):
    """The server's tomorrow is the user's today for a few hours every evening
    east of it -- rejecting that is a confusing error for nothing done wrong."""
    entry = schemas.CashBalanceEntryCreate(entry_date=date.today() + timedelta(days=1), balance=1)
    assert entry.entry_date == date.today()


def test_a_past_date_is_untouched(schemas):
    when = date.today() - timedelta(days=400)
    assert schemas.CashBalanceEntryCreate(entry_date=when, balance=1).entry_date == when


# --------------------------------------------------------------- length limits
@pytest.mark.parametrize(
    "factory,field,limit",
    [
        (lambda s, v: s.PortfolioCreate(name=v, base_currency="EUR"), "name", 200),
        (lambda s, v: s.AssetCreate(name="A", ticker=v), "ticker", 20),
        (lambda s, v: s.AssetCreate(name="A", isin=v), "isin", 20),
        (lambda s, v: s.ExpenseCategoryCreate(name=v), "name", 200),
    ],
)
def test_free_text_is_capped(schemas, factory, field, limit):
    factory(schemas, "x" * limit)  # exactly at the limit is fine
    with pytest.raises(ValueError):
        factory(schemas, "x" * (limit + 1))


def test_reading_back_a_longer_stored_value_still_works(schemas):
    """The caps are on writes only. An *Out schema with the same max_length
    would make an over-long row already in the database unreadable."""
    out = schemas.AssetOut(id="1", name="N" * 500, asset_class="ETF", currency="EUR")
    assert len(out.name) == 500
