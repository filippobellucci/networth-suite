from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from .. import models, reports, schemas
from ..database import get_db
from ..helpers import _get_or_404
from .expenses import _category_namer, compute_refund_adjustments

router = APIRouter()


# ---------------------------------------------------------------- Budgets
@router.get("/budgets", response_model=List[schemas.BudgetOut])
def list_budgets(db: Session = Depends(get_db)):
    return db.query(models.Budget).order_by(models.Budget.created_at).all()


@router.post("/budgets", response_model=schemas.BudgetOut)
def create_budget(payload: schemas.BudgetCreate, db: Session = Depends(get_db)):
    _get_or_404(db, models.ExpenseCategory, payload.category_id, "Expense category")
    if db.query(models.Budget).filter(models.Budget.category_id == payload.category_id).first():
        raise HTTPException(409, "This category already has a budget -- edit that one instead")
    budget = models.Budget(category_id=payload.category_id, amount=payload.amount, currency=payload.currency)
    db.add(budget)
    db.commit()
    db.refresh(budget)
    return budget


@router.patch("/budgets/{budget_id}", response_model=schemas.BudgetOut)
def update_budget(budget_id: str, payload: schemas.BudgetUpdate, db: Session = Depends(get_db)):
    budget = _get_or_404(db, models.Budget, budget_id, "Budget")
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(budget, k, v)
    db.commit()
    db.refresh(budget)
    return budget


@router.delete("/budgets/{budget_id}", status_code=204)
def delete_budget(budget_id: str, db: Session = Depends(get_db)):
    db.delete(_get_or_404(db, models.Budget, budget_id, "Budget"))
    db.commit()


@router.get("/budgets/progress", response_model=schemas.BudgetProgress)
async def budget_progress(
    month: Optional[str] = Query(None, pattern=r"^\d{4}-(0[1-9]|1[0-2])$"),
    portfolio_id: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """
    Each budget against what its category has spent in `month` (YYYY-MM,
    default the current one), counted like /expenses/summary and converted
    into the budget's own currency. NEAR from 90% of the budget, OVER past
    it. `elapsed_pct` -- how much of the month has gone by -- is what makes
    "60% spent" mean something: alarming on the 5th, fine on the 25th.
    """
    today = date.today()
    start = date(int(month[:4]), int(month[5:]), 1) if month else reports.month_start(today)
    end = reports.month_end(start)
    if start > today:
        elapsed = 0.0
    elif end < today:
        elapsed = 100.0
    else:
        elapsed = round(today.day / end.day * 100, 1)

    budgets = db.query(models.Budget).order_by(models.Budget.created_at).all()
    adjustments = compute_refund_adjustments(db)
    spent_by_currency: dict[str, dict[Optional[str], float]] = {}
    for currency in {b.currency for b in budgets}:
        found = await reports.flows(db, start, min(end, today), portfolio_id, currency, adjustments)
        totals: dict[Optional[str], float] = {}
        for f in found:
            if not f.income:
                totals[f.txn.category_id] = totals.get(f.txn.category_id, 0.0) + f.amount
        spent_by_currency[currency] = totals

    name_of = _category_namer(db)
    items = []
    for b in budgets:
        spent = round(spent_by_currency[b.currency].get(b.category_id, 0.0), 2)
        percent = round(spent / b.amount * 100, 1) if b.amount else 0.0
        items.append(schemas.BudgetProgressItem(
            budget_id=b.id, category_id=b.category_id, category_name=name_of(b.category_id),
            currency=b.currency, budget=b.amount, spent=spent, remaining=round(b.amount - spent, 2),
            percent=percent, status="OVER" if spent > b.amount else ("NEAR" if percent >= 90 else "OK"),
        ))
    return schemas.BudgetProgress(month=start.strftime("%Y-%m"), elapsed_pct=elapsed, items=items)
