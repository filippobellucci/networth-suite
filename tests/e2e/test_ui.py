"""
The built frontend, in a real browser, against the whole stack.

Deliberately few tests, each checking something no other tier can see: that
the pages render at all, that a figure typed by hand survives the round trip
to the screen, and that a refusal from the server arrives as a sentence a
person can act on.

Everything that can be checked without a browser is checked without one --
this tier is slow, and a large suite here would be a slow suite that fails
for reasons unrelated to the change being made.
"""
from __future__ import annotations

import pytest

pytestmark = [pytest.mark.e2e, pytest.mark.slow]

PAGES = ["/", "/portfolios", "/assets", "/allocation", "/geo-allocation",
         "/expenses", "/historical", "/settings"]


@pytest.mark.parametrize("path", PAGES)
def test_every_page_renders(page, path):
    page.goto(f"{page.base}{path}", wait_until="networkidle")
    page.wait_for_timeout(300)
    assert page.errors == [], f"{path} raised {page.errors}"
    assert page.failures == [], f"{path} had failed requests: {page.failures}"
    body = page.content()
    assert "[object Object]" not in body, f"{path} rendered a raw object"
    assert "Could not reach the gateway" not in body, f"{path} could not reach the backend"


def test_a_direct_link_to_a_route_works_on_reload(page):
    """The app's /assets route and the bundle's own /assets directory collide;
    the static server has to rewrite unknown paths to index.html."""
    page.goto(f"{page.base}/assets", wait_until="networkidle")
    assert page.locator("h1").first.inner_text().strip() != ""
    assert page.errors == []


def test_creating_a_portfolio_and_seeing_it_listed(page):
    page.goto(f"{page.base}/portfolios", wait_until="networkidle")
    page.get_by_role("button", name="+ New portfolio", exact=True).click()
    page.locator("form input").first.fill("E2E portfolio")
    page.get_by_role("button", name="Create", exact=True).click()
    page.wait_for_timeout(1200)
    assert "E2E portfolio" in page.content()
    assert page.errors == []


def test_a_server_refusal_reads_as_a_sentence(page):
    """Every validation failure used to reach the user as the literal text
    "[object Object]" -- on fields where nothing in the UI says the limit
    either, so it told them precisely nothing."""
    page.goto(f"{page.base}/assets", wait_until="networkidle")
    page.get_by_role("button", name="+ New asset", exact=True).click()
    page.locator("form input").first.fill("Asset with an over-long ticker")
    page.locator('form input[placeholder="e.g. SWDA.MI"]').fill("A" * 25)
    page.get_by_role("button", name="Create asset", exact=True).click()
    page.wait_for_timeout(1200)

    message = " ".join(page.locator("form p.text-loss").all_text_contents())
    assert "[object Object]" not in message
    assert "20 characters" in message, f"unhelpful message: {message!r}"


def test_a_hand_typed_amount_reaches_the_screen_intact(page):
    """The number a person types goes through the locale parser on its way
    out and the money formatter on its way back; this is the only test that
    exercises both ends against the real backend."""
    page.goto(f"{page.base}/portfolios", wait_until="networkidle")
    page.get_by_role("button", name="+ New portfolio", exact=True).click()
    page.locator("form input").first.fill("E2E amounts")
    page.get_by_role("button", name="Create", exact=True).click()
    page.wait_for_timeout(1200)

    page.get_by_role("link", name="E2E amounts", exact=True).first.click()
    page.wait_for_load_state("networkidle")

    page.get_by_role("button", name="+ Add", exact=True).first.click()
    page.wait_for_timeout(400)
    form = page.locator("form").first
    form.locator("input").first.fill("E2E account")
    # typed the European way, with a comma for the decimal point
    page.get_by_placeholder("0,00").or_(form.locator("input").nth(1)).first.fill("1 234,50")
    page.get_by_role("button", name="Create", exact=True).click()
    page.wait_for_timeout(1500)

    body = page.content()
    assert "1,234.5" in body, "the typed amount did not survive: looked for 1,234.5 in the page"
    assert page.errors == []


def test_the_dashboard_shows_a_total_rather_than_an_error(page):
    page.goto(f"{page.base}/", wait_until="networkidle")
    page.wait_for_timeout(500)
    body = page.content()
    assert "Total net worth" in body
    assert "Could not reach the gateway" not in body
    assert page.errors == []


def test_mapping_a_merchant_categorizes_its_transactions(page, core_http):
    """The monthly routine end to end: a merchant bank-sync captured shows up
    under Expenses -> Merchants as one to map, and picking a category for it
    categorizes the transaction already logged."""
    from datetime import date, timedelta

    def ok(r):
        assert r.status_code < 300, r.text
        return r.json()

    p = ok(core_http.post("/portfolios", json={"name": "Merchants e2e", "base_currency": "EUR"}))
    acc = ok(core_http.post(f"/portfolios/{p['id']}/cash-accounts", json={"name": "Revolut e2e", "currency": "EUR"}))
    cat = ok(core_http.post("/expense-categories", json={"name": "Food delivery e2e"}))
    txn = ok(core_http.post(f"/cash-accounts/{acc['id']}/transactions", json={
        "entry_date": (date.today() - timedelta(days=1)).isoformat(), "direction": "EXPENSE",
        "amount": 22.34, "counterparty": "Deliveroo E2E"}))

    page.goto(f"{page.base}/expenses", wait_until="networkidle")
    page.get_by_role("button", name="Merchants", exact=True).click()
    page.wait_for_timeout(800)
    row = page.locator("tr", has_text="Deliveroo E2E")
    assert row.count() == 1, "an unmapped merchant is listed under To map"
    row.locator("select").select_option(label="Food delivery e2e")
    page.wait_for_timeout(1200)

    assert "1 transaction categorized" in page.content()
    assert page.locator("tr", has_text="Deliveroo E2E").count() == 0, "mapped: off the To map list"
    assert ok(core_http.get(f"/cash-transactions/{txn['id']}"))["category_id"] == cat["id"]
    assert page.errors == [] and page.failures == []
