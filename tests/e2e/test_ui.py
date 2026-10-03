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

PAGES = ["/", "/portfolios", "/assets", "/allocation", "/historical-networth",
         "/expenses", "/settings"]


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


def _ledger(core_http, name):
    """A portfolio of its own, with a Revolut-like and a second account."""
    from datetime import date, timedelta

    def ok(r):
        assert r.status_code < 300, r.text
        return r.json()

    p = ok(core_http.post("/portfolios", json={"name": name, "base_currency": "EUR"}))
    rev = ok(core_http.post(f"/portfolios/{p['id']}/cash-accounts", json={"name": f"{name} Revolut", "currency": "EUR"}))
    other = ok(core_http.post(f"/portfolios/{p['id']}/cash-accounts", json={"name": f"{name} Fineco", "currency": "EUR"}))
    day = (date.today() - timedelta(days=1)).isoformat()

    def txn(direction, amount, note, **kw):
        return ok(core_http.post(f"/cash-accounts/{rev['id']}/transactions",
                                 json={"entry_date": day, "direction": direction, "amount": amount, "note": note, **kw}))
    return p, rev, other, txn, ok


def _open_log(page, portfolio_name):
    page.goto(f"{page.base}/expenses", wait_until="networkidle")
    page.locator("select").first.select_option(label=portfolio_name)
    page.wait_for_timeout(800)


def test_editing_a_transactions_category_from_the_log(page, core_http):
    p, rev, other, txn, ok = _ledger(core_http, "Edit e2e")
    cat = ok(core_http.post("/expense-categories", json={"name": "Edit e2e cat"}))
    t = txn("EXPENSE", 7.2, "Unicoop edit e2e")

    _open_log(page, "Edit e2e")
    page.locator("tr", has_text="Unicoop edit e2e").get_by_role("button", name="Edit").click()
    form = page.get_by_label("Edit transaction")
    form.locator("select").select_option(label="Edit e2e cat")
    form.locator("input").nth(2).fill("Unicoop edited")
    form.get_by_role("button", name="Save changes").click()
    page.wait_for_timeout(1000)

    got = ok(core_http.get(f"/cash-transactions/{t['id']}"))
    assert got["category_id"] == cat["id"] and got["note"] == "Unicoop edited"
    assert got["amount"] == 7.2, "an untouched amount is not re-sent"
    assert page.locator("tr", has_text="Unicoop edited").count() == 1
    assert page.errors == [] and page.failures == []


def test_bulk_categorizing_from_the_uncategorized_filter(page, core_http):
    p, rev, other, txn, ok = _ledger(core_http, "Bulk e2e")
    cat = ok(core_http.post("/expense-categories", json={"name": "Bulk e2e cat"}))
    a = txn("EXPENSE", 1, "bulk a")
    b = txn("EXPENSE", 2, "bulk b")
    txn("EXPENSE", 3, "bulk already", category_id=cat["id"])

    _open_log(page, "Bulk e2e")
    page.get_by_role("button", name="Uncategorized", exact=True).click()
    page.wait_for_timeout(800)
    assert page.locator("tr", has_text="bulk already").count() == 0, "categorized ones are filtered out"
    for note in ("bulk a", "bulk b"):
        page.locator("tr", has_text=note).get_by_label("Select for bulk categorize").check()
    bar = page.get_by_label("Bulk categorize")
    bar.locator("select").select_option(label="Bulk e2e cat")
    bar.get_by_role("button", name="Apply to selected").click()
    page.wait_for_timeout(1000)

    assert "2 transactions moved to Bulk e2e cat" in page.content()
    assert "Nothing left to categorize" in page.content()
    for t in (a, b):
        assert ok(core_http.get(f"/cash-transactions/{t['id']}"))["category_id"] == cat["id"]
    assert page.errors == [] and page.failures == []


def test_marking_a_bank_top_up_as_a_transfer(page, core_http):
    p, rev, other, txn, ok = _ledger(core_http, "Transfer e2e")
    t = txn("INCOME", 500, "soldi transfer e2e", counterparty="BELLUCCI FILIPPO")

    _open_log(page, "Transfer e2e")
    page.locator("tr", has_text="soldi transfer e2e").get_by_role("button", name="⇄ Transfer").click()
    form = page.get_by_label("Convert to transfer")
    form.locator("select").select_option(label="Transfer e2e Fineco (EUR)")
    form.get_by_role("button", name="⇄ Make it a transfer").click()
    page.wait_for_timeout(1000)

    assert ok(core_http.get(f"/cash-transactions/{t['id']}"))["transfer_id"]
    legs = ok(core_http.get(f"/cash-accounts/{other['id']}/transactions"))
    assert len(legs) == 1 and legs[0]["direction"] == "EXPENSE" and legs[0]["amount"] == 500
    assert "Now a transfer" in page.content()
    assert page.errors == [] and page.failures == []


def test_a_bank_link_needing_attention_is_announced(page):
    """The test stack's bank-sync has one link that was never authorized."""
    page.goto(f"{page.base}/", wait_until="networkidle")
    page.wait_for_timeout(500)
    alerts = page.get_by_label("Bank sync alerts")
    assert alerts.count() == 1
    assert "Test bank is configured but not authorized yet" in alerts.inner_text()
    assert alerts.get_by_role("link", name="Authorize ↗").get_attribute("href").endswith("/authorize/Test%20bank")
    assert page.errors == []


def test_searching_the_log_and_exporting_what_is_found(page, core_http):
    p, rev, other, txn, ok = _ledger(core_http, "Search e2e")
    txn("EXPENSE", 7.2, "Unicoop search e2e", counterparty="Unicoop Firenze")
    txn("EXPENSE", 22.34, "Deliveroo search e2e")

    _open_log(page, "Search e2e")
    page.get_by_label("Search transactions").fill("unicoop")
    page.wait_for_timeout(1000)
    assert page.locator("tr", has_text="Unicoop search e2e").count() == 1
    assert page.locator("tr", has_text="Deliveroo search e2e").count() == 0

    with page.expect_download() as dl:
        page.get_by_role("button", name="Export CSV").click()
    content = open(dl.value.path(), encoding="utf-8-sig").read()
    assert "Unicoop search e2e" in content and "Deliveroo search e2e" not in content, "the export follows the search"
    assert page.errors == [] and page.failures == []


def test_budgets_tab_and_the_over_budget_banner(page, core_http):
    from datetime import date

    p, rev, other, txn, ok = _ledger(core_http, "Budget e2e")
    cat = ok(core_http.post("/expense-categories", json={"name": "Budget e2e cat"}))
    core_http.post(f"/cash-accounts/{rev['id']}/transactions", json={
        "entry_date": date.today().replace(day=1).isoformat(), "direction": "EXPENSE",
        "amount": 120, "category_id": cat["id"], "note": "budget e2e"})

    page.goto(f"{page.base}/expenses", wait_until="networkidle")
    page.get_by_role("button", name="Budgets", exact=True).click()
    page.wait_for_timeout(600)
    form = page.get_by_label("Add budget")
    form.locator("select").select_option(label="Budget e2e cat")
    form.locator("input").fill("100")
    form.get_by_role("button", name="Add budget").click()
    page.wait_for_timeout(1000)
    row = page.get_by_label("Budget Budget e2e cat")
    assert "Over budget" in row.inner_text()

    page.get_by_role("button", name="Log", exact=True).click()
    page.wait_for_timeout(800)
    banner = page.get_by_label("Budget alerts")
    assert "Over budget this month" in banner.inner_text() and "Budget e2e cat" in banner.inner_text()
    banner.get_by_role("button", name="See budgets").click()
    page.wait_for_timeout(500)
    assert page.get_by_label("Add budget").count() == 1
    assert page.errors == [] and page.failures == []


def test_recurring_and_monthly_views_render(page, core_http):
    from datetime import date, timedelta

    p, rev, other, txn, ok = _ledger(core_http, "Recurring e2e")
    for i in range(4):
        core_http.post(f"/cash-accounts/{rev['id']}/transactions", json={
            "entry_date": (date.today() - timedelta(days=30 * i + 2)).isoformat(), "direction": "EXPENSE",
            "amount": 9.99, "counterparty": "Spotify e2e"})

    page.goto(f"{page.base}/expenses", wait_until="networkidle")
    page.get_by_role("button", name="Recurring", exact=True).click()
    page.wait_for_timeout(600)
    page.get_by_label("Portfolio").select_option(label="Recurring e2e")
    page.wait_for_timeout(1000)
    assert page.locator("tr", has_text="Spotify e2e").count() == 1
    assert "Monthly" in page.locator("tr", has_text="Spotify e2e").inner_text()

    page.get_by_role("button", name="History", exact=True).click()
    page.wait_for_timeout(1200)
    assert page.get_by_text("Month by month").count() == 1
    assert page.get_by_role("img", name="Monthly income and spending").count() == 1
    assert page.errors == [] and page.failures == []
