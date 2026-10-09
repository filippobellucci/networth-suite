"""
The out-of-app alert for a budget going over (AGE-11): the Budgets page
only warns while someone has it open, so the scheduler sends one email,
through `alerts.check_budgets_over`, the first time a budget's spending
for the current month crosses its limit.

The SMTP channel itself (shared/notify.py) is exercised in
tests/unit/test_notify.py; this only checks the dedup bookkeeping -- sent
once, not every time the job runs, and resuming next month -- and that the
message carries no amount or balance, since it leaves the owner's machine.
"""
from __future__ import annotations

import pytest

from helpers import add_transaction, make_account, make_portfolio, ok
from service_loader import service_module

pytestmark = pytest.mark.integration


@pytest.fixture
def alerts(core):
    return service_module("core_app", "alerts")


@pytest.fixture
def sent(alerts, monkeypatch):
    messages: list[tuple[str, str]] = []
    monkeypatch.setattr(alerts.notify, "send", lambda subject, body: messages.append((subject, body)) or True)
    return messages


@pytest.fixture
async def budget_ctx(api):
    p = await make_portfolio(api)
    acc = await make_account(api, p["id"])
    cat = await ok(await api.post("/expense-categories", json={"name": "Groceries"}))
    budget = await ok(await api.post("/budgets", json={"category_id": cat["id"], "amount": 50}))
    return {"acc": acc["id"], "cat": cat["id"], "budget": budget["id"]}


async def test_an_exceeded_budget_alerts_once(api, db_session, alerts, sent, budget_ctx):
    await add_transaction(api, budget_ctx["acc"], "EXPENSE", 80, category_id=budget_ctx["cat"])

    await alerts.check_budgets_over(db_session)
    assert len(sent) == 1
    _, body = sent[0]
    assert "Groceries" in body

    # Running the job again this same month must not repeat the alert.
    await alerts.check_budgets_over(db_session)
    await alerts.check_budgets_over(db_session)
    assert len(sent) == 1


async def test_the_alert_carries_no_amount_or_balance(api, db_session, alerts, sent, budget_ctx):
    """An email passes through machines that aren't the owner's own
    (CLAUDE.md principle 3) -- it may name the category, never a figure."""
    await add_transaction(api, budget_ctx["acc"], "EXPENSE", 80, category_id=budget_ctx["cat"])
    await alerts.check_budgets_over(db_session)

    assert len(sent) == 1
    _, body = sent[0]
    for forbidden in ("80", "50", "30"):
        assert forbidden not in body


async def test_a_budget_under_its_limit_does_not_alert(api, db_session, alerts, sent, budget_ctx):
    await add_transaction(api, budget_ctx["acc"], "EXPENSE", 20, category_id=budget_ctx["cat"])
    await alerts.check_budgets_over(db_session)
    assert sent == []


async def test_a_new_month_alerts_again(api, db_session, alerts, sent, budget_ctx):
    """One alert per (budget, month): `over_alerted_month` is a free-form
    string compared against the current month, not cleared on a timer, so
    next month's first overspend is unwarned-about on its own."""
    await add_transaction(api, budget_ctx["acc"], "EXPENSE", 80, category_id=budget_ctx["cat"])
    await alerts.check_budgets_over(db_session)
    assert len(sent) == 1

    core_app_models = service_module("core_app", "models")
    budget = db_session.get(core_app_models.Budget, budget_ctx["budget"])
    budget.over_alerted_month = "2000-01"  # simulates "that was a past month"
    db_session.commit()

    await alerts.check_budgets_over(db_session)
    assert len(sent) == 2
