"""
Out-of-app alert for a budget going over (AGE-11): the Budgets page only
warns while someone has it open, and a budget blown on the 3rd of the
month can otherwise go unnoticed until the next time the app is opened.
Reuses `routers.budgets.budget_progress` rather than recomputing "how much
has this category spent" a second way (see CLAUDE.md -- that logic is
already exercised by its own tests).

Sent once per (budget, calendar month): `Budget.over_alerted_month` records
the last month it fired for, so the same overspend doesn't alert again
every scheduler cycle, and next month's first overspend alerts on its own
without anything to reset.
"""
from datetime import date

from sqlalchemy.orm import Session

from . import models
from .routers.budgets import budget_progress
from shared import notify


async def check_budgets_over(db: Session) -> None:
    month = date.today().strftime("%Y-%m")
    progress = await budget_progress(month=None, portfolio_id=None, db=db)
    for item in progress.items:
        if item.status != "OVER":
            continue
        budget = db.get(models.Budget, item.budget_id)
        if budget is None or budget.over_alerted_month == month:
            continue
        sent = notify.send(
            "Net Worth Suite: budget exceeded",
            f'The "{item.category_name}" budget for {progress.month} has been exceeded. '
            "Open the app for the details.",
        )
        if sent:
            budget.over_alerted_month = month
    db.commit()
