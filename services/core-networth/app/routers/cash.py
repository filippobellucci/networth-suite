from datetime import datetime
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_db
from ..helpers import _get_or_404

router = APIRouter()


# ---------------------------------------------------------------- Cash accounts
@router.post("/portfolios/{portfolio_id}/cash-accounts", response_model=schemas.CashAccountOut)
def create_cash_account(portfolio_id: str, payload: schemas.CashAccountCreate, db: Session = Depends(get_db)):
    _get_or_404(db, models.Portfolio, portfolio_id, "Portfolio")
    acc = models.CashAccount(portfolio_id=portfolio_id, **payload.model_dump())
    db.add(acc)
    db.commit()
    db.refresh(acc)
    return acc


@router.get("/portfolios/{portfolio_id}/cash-accounts", response_model=List[schemas.CashAccountOut])
def list_cash_accounts(portfolio_id: str, include_archived: bool = False, db: Session = Depends(get_db)):
    """
    Active accounts only by default -- that's what every picker offering a
    place to log something wants.

    `include_archived=True` is for the read-only views that describe rows
    which already exist: an archived account's past transactions are still
    real, and need their account's name and currency to be shown.
    """
    q = db.query(models.CashAccount).filter(models.CashAccount.portfolio_id == portfolio_id)
    if not include_archived:
        q = q.filter(models.CashAccount.archived_at.is_(None))
    return q.all()


@router.patch("/cash-accounts/{account_id}", response_model=schemas.CashAccountOut)
def update_cash_account(account_id: str, payload: schemas.CashAccountUpdate, db: Session = Depends(get_db)):
    acc = _get_or_404(db, models.CashAccount, account_id, "Cash account")
    data = payload.model_dump(exclude_unset=True)
    # Pension Fund accounts never accept transactions, and XIRR reads their
    # balance changes as return rather than contributions -- so an account
    # that already has transactions can't be retagged into Pension Fund.
    if (
        data.get("category") == models.AllocationCategory.PENSION_FUND
        and acc.category != models.AllocationCategory.PENSION_FUND
        and db.query(models.CashTransaction.id).filter(models.CashTransaction.account_id == account_id).first()
    ):
        raise HTTPException(
            400,
            "Can't tag this account as Pension Fund: it already has transaction history, and Pension Fund "
            "accounts never accept transactions.",
        )
    for k, v in data.items():
        setattr(acc, k, v)
    db.commit()
    db.refresh(acc)
    return acc


@router.delete("/cash-accounts/{account_id}", status_code=204)
def delete_cash_account(account_id: str, db: Session = Depends(get_db)):
    acc = _get_or_404(db, models.CashAccount, account_id, "Cash account")
    # Archived, not hard-deleted -- see CashAccount.archived_at's docstring.
    # It disappears from every current list/total from now on, but its
    # existing balance/transaction rows stay untouched so past dates still
    # value correctly.
    #
    # now(), not utcnow(): its DATE is compared against local calendar days
    # (`as_of < archived_at.date()` in valuation.py and xirr.py).
    acc.archived_at = datetime.now()
    db.commit()


@router.post("/cash-accounts/{account_id}/balances", response_model=schemas.CashBalanceEntryOut)
def add_cash_balance(account_id: str, payload: schemas.CashBalanceEntryCreate, db: Session = Depends(get_db)):
    acc = _get_or_404(db, models.CashAccount, account_id, "Cash account")
    if acc.archived_at is not None:
        raise HTTPException(400, "This account has been removed and no longer accepts new balances")
    entry = models.CashBalanceEntry(account_id=account_id, **payload.model_dump())
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry
