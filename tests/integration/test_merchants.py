"""
Merchant rules: categorizing by counterparty name.

Revolut, through Enable Banking, sends card payments with no merchant category
code at all -- observed on a live account across pending and booked versions
alike -- so the counterparty's name is the only thing left to categorize by.
These tests pin the behaviour the monthly "map what's new" routine relies on:
names that only differ in case are one merchant, saving a rule fixes the
merchant's past transactions without touching any categorized by hand, and an
EXACT rule or an ignored one always beats a broader CONTAINS rule.
"""
from __future__ import annotations

import pytest

from helpers import add_transaction, days_ago, make_account, make_portfolio, ok

pytestmark = pytest.mark.integration


@pytest.fixture
async def ctx(api, feed):
    p = await make_portfolio(api)
    acc = await make_account(api, p["id"])
    cats = {}
    for name in ("Spesa", "Bar", "Assicurazioni", "Stipendio"):
        cats[name] = (await ok(await api.post("/expense-categories", json={"name": name})))["id"]
    return {"account": acc["id"], "cats": cats}


async def spend(api, ctx, merchant, amount=10, on=None, **kw):
    return await add_transaction(api, ctx["account"], "EXPENSE", amount, on=on or days_ago(1),
                                 counterparty=merchant, **kw)


async def rule(api, pattern, match_type="EXACT", expected=200, **kw):
    return await ok(await api.post("/merchant-rules", json={"pattern": pattern, "match_type": match_type, **kw}),
                    expected)


async def merchant(api, name_fragment):
    rows = await ok(await api.get("/merchants"))
    return next(m for m in rows if name_fragment.casefold() in m["name"].casefold())


# ---------------------------------------------------------------- the list
async def test_a_counterparty_shows_up_as_one_to_map(api, ctx):
    await spend(api, ctx, "Unicoop Firenze-Ponsacco", 7.20)
    m = await merchant(api, "unicoop")
    assert m["status"] == "UNMAPPED" and m["rule"] is None
    assert m["expense_count"] == 1 and m["expense_total"] == 7.20 and m["uncategorized_count"] == 1


async def test_names_differing_only_in_case_and_spacing_are_one_merchant(api, ctx):
    """Revolut's pending vs booked spelling of the very same store."""
    await spend(api, ctx, "Unicoop Firenze-Ponsacco", on=days_ago(3))
    await spend(api, ctx, "Unicoop  Firenze-ponsacco", on=days_ago(1))
    rows = await ok(await api.get("/merchants"))
    assert len(rows) == 1
    assert rows[0]["expense_count"] == 2
    assert rows[0]["name"] == "Unicoop  Firenze-ponsacco", "the latest spelling is the one shown"


async def test_income_is_listed_with_its_sender(api, ctx):
    await add_transaction(api, ctx["account"], "INCOME", 1500, on=days_ago(2), counterparty="ACME SPA")
    m = await merchant(api, "acme")
    assert m["income_count"] == 1 and m["income_total"] == 1500 and m["expense_count"] == 0


async def test_transactions_logged_by_hand_are_not_merchants(api, ctx):
    await add_transaction(api, ctx["account"], "EXPENSE", 5, on=days_ago(1), note="cash")
    assert await ok(await api.get("/merchants")) == []


# ------------------------------------------------------------ saving a rule
async def test_a_rule_categorizes_the_merchants_past_transactions(api, ctx):
    t1 = await spend(api, ctx, "Deliveroo", on=days_ago(20))
    t2 = await spend(api, ctx, "DELIVEROO", on=days_ago(5))
    saved = await rule(api, "Deliveroo", category_id=ctx["cats"]["Bar"])
    assert saved["applied"] == 2
    for t in (t1, t2):
        assert (await ok(await api.get(f"/cash-transactions/{t['id']}")))["category_id"] == ctx["cats"]["Bar"]


async def test_a_category_set_by_hand_is_never_overwritten(api, ctx):
    hand = await spend(api, ctx, "Xsolla", category_id=ctx["cats"]["Spesa"])
    other = await spend(api, ctx, "Xsolla")
    saved = await rule(api, "xsolla", category_id=ctx["cats"]["Bar"])
    assert saved["applied"] == 1
    assert (await ok(await api.get(f"/cash-transactions/{hand['id']}")))["category_id"] == ctx["cats"]["Spesa"]
    assert (await ok(await api.get(f"/cash-transactions/{other['id']}")))["category_id"] == ctx["cats"]["Bar"]


async def test_apply_to_past_can_be_turned_off(api, ctx):
    t = await spend(api, ctx, "Deliveroo")
    saved = await rule(api, "Deliveroo", category_id=ctx["cats"]["Bar"], apply_to_past=False)
    assert saved["applied"] == 0
    assert (await ok(await api.get(f"/cash-transactions/{t['id']}")))["category_id"] is None


async def test_a_new_transaction_of_a_mapped_merchant_arrives_categorized(api, ctx):
    await rule(api, "Unicoop Firenze-Ponsacco", category_id=ctx["cats"]["Spesa"])
    t = await spend(api, ctx, "UNICOOP FIRENZE-PONSACCO")
    assert t["category_id"] == ctx["cats"]["Spesa"]


async def test_a_category_given_on_creation_wins_over_the_rule(api, ctx):
    """bank-sync sends one when the bank's MCC maps to a category."""
    await rule(api, "Unicoop", category_id=ctx["cats"]["Spesa"])
    t = await spend(api, ctx, "Unicoop", category_id=ctx["cats"]["Bar"])
    assert t["category_id"] == ctx["cats"]["Bar"]


async def test_setting_the_counterparty_later_categorizes_like_creation_would(api, ctx):
    """How bank-sync fills in transactions captured before it sent one."""
    await rule(api, "Deliveroo", category_id=ctx["cats"]["Bar"])
    t = await add_transaction(api, ctx["account"], "EXPENSE", 22.34, on=days_ago(1))
    patched = await ok(await api.patch(f"/cash-transactions/{t['id']}", json={"counterparty": "Deliveroo"}))
    assert patched["counterparty"] == "Deliveroo"
    assert patched["category_id"] == ctx["cats"]["Bar"]


# ----------------------------------------------------------- contains rules
async def test_a_contains_rule_covers_every_store_of_a_chain(api, ctx):
    await spend(api, ctx, "Unicoop Firenze-Ponsacco")
    await spend(api, ctx, "Unicoop Firenze-Pontedera")
    saved = await rule(api, "unicoop", "CONTAINS", category_id=ctx["cats"]["Spesa"])
    assert saved["applied"] == 2
    assert all(m["status"] == "MAPPED" for m in await ok(await api.get("/merchants")))


async def test_an_exact_rule_beats_a_contains_rule(api, ctx):
    await rule(api, "coop", "CONTAINS", category_id=ctx["cats"]["Spesa"])
    await rule(api, "Coop Assicurazioni", category_id=ctx["cats"]["Assicurazioni"])
    t = await spend(api, ctx, "Coop Assicurazioni")
    assert t["category_id"] == ctx["cats"]["Assicurazioni"]


async def test_the_longest_contains_rule_wins(api, ctx):
    await rule(api, "coop assicurazioni", "CONTAINS", category_id=ctx["cats"]["Assicurazioni"])
    await rule(api, "coop", "CONTAINS", category_id=ctx["cats"]["Spesa"])
    assert (await spend(api, ctx, "Coop Assicurazioni Spa"))["category_id"] == ctx["cats"]["Assicurazioni"]
    assert (await spend(api, ctx, "Coop Centro Italia"))["category_id"] == ctx["cats"]["Spesa"]


async def test_a_contains_rule_leaves_merchants_with_their_own_rule_alone(api, ctx):
    t = await spend(api, ctx, "Coop Assicurazioni")
    await rule(api, "Coop Assicurazioni", ignored=True)
    saved = await rule(api, "coop", "CONTAINS", category_id=ctx["cats"]["Spesa"])
    assert saved["applied"] == 0
    assert (await ok(await api.get(f"/cash-transactions/{t['id']}")))["category_id"] is None


async def test_a_contains_rule_needs_three_characters(api, ctx):
    await rule(api, "co", "CONTAINS", expected=400, category_id=ctx["cats"]["Spesa"])


# --------------------------------------------------------------- ignoring
async def test_an_ignored_merchant_stays_uncategorized_and_off_the_to_do_list(api, ctx):
    await add_transaction(api, ctx["account"], "INCOME", 500, on=days_ago(1), counterparty="BELLUCCI FILIPPO")
    await rule(api, "Bellucci Filippo", ignored=True)
    m = await merchant(api, "bellucci")
    assert m["status"] == "IGNORED"
    t = await add_transaction(api, ctx["account"], "INCOME", 40, on=days_ago(1), counterparty="Bellucci Filippo")
    assert t["category_id"] is None


async def test_a_rule_is_either_a_category_or_ignored(api, ctx):
    await rule(api, "x shop", expected=400)
    await rule(api, "x shop", expected=400, category_id=ctx["cats"]["Bar"], ignored=True)
    await rule(api, "x shop", expected=404, category_id="no-such-category")


async def test_the_same_rule_cannot_be_created_twice(api, ctx):
    await rule(api, "Deliveroo", category_id=ctx["cats"]["Bar"])
    await rule(api, " DELIVEROO ", expected=409, category_id=ctx["cats"]["Spesa"])


# ---------------------------------------------------------------- editing
async def test_changing_a_rule_fills_uncategorized_but_leaves_categorized_alone_by_default(api, ctx):
    t = await spend(api, ctx, "Deliveroo")
    saved = await rule(api, "Deliveroo", category_id=ctx["cats"]["Bar"])
    later = await spend(api, ctx, "Deliveroo", category_id=None)
    assert later["category_id"] == ctx["cats"]["Bar"]
    updated = await ok(await api.patch(f"/merchant-rules/{saved['rule']['id']}",
                                       json={"category_id": ctx["cats"]["Spesa"]}))
    assert updated["applied"] == 0
    assert (await ok(await api.get(f"/cash-transactions/{t['id']}")))["category_id"] == ctx["cats"]["Bar"]


async def test_changing_a_rule_can_move_what_it_had_categorized(api, ctx):
    t = await spend(api, ctx, "Deliveroo")
    hand = await spend(api, ctx, "Deliveroo", category_id=ctx["cats"]["Stipendio"])
    saved = await rule(api, "Deliveroo", category_id=ctx["cats"]["Bar"])
    updated = await ok(await api.patch(f"/merchant-rules/{saved['rule']['id']}",
                                       json={"category_id": ctx["cats"]["Spesa"], "recategorize_previous": True}))
    assert updated["applied"] == 1
    assert (await ok(await api.get(f"/cash-transactions/{t['id']}")))["category_id"] == ctx["cats"]["Spesa"]
    assert (await ok(await api.get(f"/cash-transactions/{hand['id']}")))["category_id"] == ctx["cats"]["Stipendio"]


async def test_ignoring_then_mapping_a_merchant(api, ctx):
    t = await spend(api, ctx, "Xsolla")
    saved = await rule(api, "Xsolla", ignored=True)
    updated = await ok(await api.patch(f"/merchant-rules/{saved['rule']['id']}",
                                       json={"category_id": ctx["cats"]["Bar"]}))
    assert updated["rule"]["ignored"] is False and updated["applied"] == 1
    assert (await ok(await api.get(f"/cash-transactions/{t['id']}")))["category_id"] == ctx["cats"]["Bar"]


async def test_deleting_a_rule_keeps_the_categories_it_gave(api, ctx):
    t = await spend(api, ctx, "Deliveroo")
    saved = await rule(api, "Deliveroo", category_id=ctx["cats"]["Bar"])
    await ok(await api.delete(f"/merchant-rules/{saved['rule']['id']}"), 204)
    assert (await ok(await api.get(f"/cash-transactions/{t['id']}")))["category_id"] == ctx["cats"]["Bar"]
    assert (await merchant(api, "deliveroo"))["status"] == "UNMAPPED"


async def test_deleting_a_category_puts_its_merchants_back_to_map(api, ctx):
    await spend(api, ctx, "Deliveroo")
    await rule(api, "Deliveroo", category_id=ctx["cats"]["Bar"])
    await ok(await api.delete(f"/expense-categories/{ctx['cats']['Bar']}"), 204)
    assert await ok(await api.get("/merchant-rules")) == []
    m = await merchant(api, "deliveroo")
    assert m["status"] == "UNMAPPED" and m["uncategorized_count"] == 1
