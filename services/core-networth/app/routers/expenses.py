import colorsys
import csv
import io
from datetime import date, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy import or_
from sqlalchemy.orm import Session

from .. import merchants, models, price_client, reports, schemas
from ..database import get_db
from ..helpers import _check_idempotency, _commit_with_idempotency, _get_or_404, _paginate, _store_idempotency

router = APIRouter()


# ---------------------------------------------------------------- Expense categories
def _next_category_color(db: Session) -> str:
    """
    Assigns each new category a color automatically -- no fixed swatch list
    to run out of. Hues are spread using the golden angle (~137.508 degrees),
    the standard trick for placing points around a circle one at a time so
    each new one lands as far as possible from every hue already assigned,
    however many categories accumulate.
    """
    n = db.query(models.ExpenseCategory).count()
    hue = (n * 137.508) % 360
    r, g, b = colorsys.hls_to_rgb(hue / 360, 0.50, 0.55)
    return f"#{int(r * 255):02x}{int(g * 255):02x}{int(b * 255):02x}"


@router.post("/expense-categories", response_model=schemas.ExpenseCategoryOut)
def create_expense_category(payload: schemas.ExpenseCategoryCreate, db: Session = Depends(get_db)):
    cat = models.ExpenseCategory(name=payload.name, color=_next_category_color(db))
    db.add(cat)
    db.commit()
    db.refresh(cat)
    return cat


@router.get("/expense-categories", response_model=List[schemas.ExpenseCategoryOut])
def list_expense_categories(db: Session = Depends(get_db)):
    return db.query(models.ExpenseCategory).order_by(models.ExpenseCategory.name).all()


@router.patch("/expense-categories/{category_id}", response_model=schemas.ExpenseCategoryOut)
def update_expense_category(category_id: str, payload: schemas.ExpenseCategoryUpdate, db: Session = Depends(get_db)):
    cat = _get_or_404(db, models.ExpenseCategory, category_id, "Expense category")
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(cat, k, v)
    db.commit()
    db.refresh(cat)
    return cat


@router.delete("/expense-categories/{category_id}", status_code=204)
def delete_expense_category(category_id: str, db: Session = Depends(get_db)):
    cat = _get_or_404(db, models.ExpenseCategory, category_id, "Expense category")
    # Only the tag goes: the transactions tagged with it stay, uncategorized.
    db.query(models.CashTransaction).filter(models.CashTransaction.category_id == category_id).update(
        {"category_id": None}
    )
    # Merchant rules pointing at it go too: their counterparties become ones
    # still to map again.
    db.query(models.MerchantRule).filter(models.MerchantRule.category_id == category_id).delete()
    db.query(models.Budget).filter(models.Budget.category_id == category_id).delete()
    db.delete(cat)
    db.commit()


# ---------------------------------------------------------------- Merchants (counterparty -> category)
def _validate_rule_target(db: Session, category_id: Optional[str], ignored: bool) -> None:
    if ignored and category_id:
        raise HTTPException(400, "A merchant is either mapped to a category or ignored, not both")
    if not ignored and not category_id:
        raise HTTPException(400, "Pick a category, or mark the merchant as ignored")
    if category_id:
        _get_or_404(db, models.ExpenseCategory, category_id, "Expense category")


@router.get("/merchants", response_model=List[schemas.MerchantOut])
def list_merchants(db: Session = Depends(get_db)):
    """
    Every counterparty seen on a transaction, with what currently decides its
    category -- the list a merchant still to map is found in. Built from the
    transactions themselves rather than kept as a separate registry, so it
    can never disagree with them. Most frequent first.
    """
    book = merchants.RuleBook(db)
    txns = (
        db.query(models.CashTransaction)
        .filter(models.CashTransaction.counterparty_key.isnot(None), models.CashTransaction.transfer_id.is_(None))
        .order_by(models.CashTransaction.entry_date, models.CashTransaction.created_at)
        .all()
    )
    groups: dict[str, dict] = {}
    for t in txns:
        g = groups.setdefault(t.counterparty_key, {
            "key": t.counterparty_key, "expense_count": 0, "income_count": 0,
            "expense_total": 0.0, "income_total": 0.0, "uncategorized_count": 0,
        })
        g["name"] = t.counterparty  # oldest-first, so the latest spelling wins
        g["last_date"] = t.entry_date
        if t.direction == models.TransactionDirection.INCOME:
            g["income_count"] += 1
            g["income_total"] += t.amount
        else:
            g["expense_count"] += 1
            g["expense_total"] += t.amount
        if t.category_id is None:
            g["uncategorized_count"] += 1

    out = []
    for key, g in groups.items():
        rule = book.match(key)
        status = "UNMAPPED" if rule is None else ("IGNORED" if rule.ignored else "MAPPED")
        out.append(schemas.MerchantOut(
            key=key, name=g["name"], status=status,
            rule=schemas.MerchantRuleOut.model_validate(rule) if rule else None,
            expense_count=g["expense_count"], income_count=g["income_count"],
            expense_total=round(g["expense_total"], 2), income_total=round(g["income_total"], 2),
            uncategorized_count=g["uncategorized_count"], last_date=g["last_date"],
        ))
    out.sort(key=lambda m: (-(m.expense_count + m.income_count), m.name.casefold()))
    return out


@router.get("/merchant-rules", response_model=List[schemas.MerchantRuleOut])
def list_merchant_rules(db: Session = Depends(get_db)):
    return db.query(models.MerchantRule).order_by(models.MerchantRule.match_type, models.MerchantRule.pattern).all()


@router.post("/merchant-rules", response_model=schemas.MerchantRuleSaved)
def create_merchant_rule(payload: schemas.MerchantRuleCreate, db: Session = Depends(get_db)):
    pattern = merchants.normalize(payload.pattern)
    if not pattern:
        raise HTTPException(400, "The merchant name can't be empty")
    if payload.match_type == models.MerchantMatchType.CONTAINS and len(pattern) < 3:
        # A one- or two-letter fragment would be part of nearly every name.
        raise HTTPException(400, "A 'contains' rule needs at least 3 characters")
    _validate_rule_target(db, payload.category_id, payload.ignored)
    existing = (
        db.query(models.MerchantRule)
        .filter(models.MerchantRule.pattern == pattern, models.MerchantRule.match_type == payload.match_type)
        .first()
    )
    if existing:
        raise HTTPException(409, "There's already a rule for this merchant -- edit that one instead")

    rule = models.MerchantRule(
        pattern=pattern, match_type=payload.match_type,
        category_id=None if payload.ignored else payload.category_id, ignored=payload.ignored,
    )
    db.add(rule)
    db.flush()
    applied = merchants.apply_to_uncategorized(db, rule) if payload.apply_to_past else 0
    db.commit()
    db.refresh(rule)
    return schemas.MerchantRuleSaved(rule=rule, applied=applied)


@router.patch("/merchant-rules/{rule_id}", response_model=schemas.MerchantRuleSaved)
def update_merchant_rule(rule_id: str, payload: schemas.MerchantRuleUpdate, db: Session = Depends(get_db)):
    rule = _get_or_404(db, models.MerchantRule, rule_id, "Merchant rule")
    data = payload.model_dump(exclude_unset=True)
    ignored = data.get("ignored", rule.ignored)
    # Picking a category un-ignores; ignoring drops the category.
    if data.get("category_id"):
        ignored = data.get("ignored", False)
    category_id = None if ignored else data.get("category_id", rule.category_id)
    _validate_rule_target(db, category_id, ignored)

    previous_category_id = rule.category_id
    rule.ignored = ignored
    rule.category_id = category_id
    db.flush()
    applied = 0
    if payload.recategorize_previous and previous_category_id != category_id:
        applied += merchants.move_from_category(db, rule, previous_category_id)
    if payload.apply_to_past:
        applied += merchants.apply_to_uncategorized(db, rule)
    db.commit()
    db.refresh(rule)
    return schemas.MerchantRuleSaved(rule=rule, applied=applied)


@router.delete("/merchant-rules/{rule_id}", status_code=204)
def delete_merchant_rule(rule_id: str, db: Session = Depends(get_db)):
    """Only the rule: transactions it already categorized keep their category."""
    db.delete(_get_or_404(db, models.MerchantRule, rule_id, "Merchant rule"))
    db.commit()


# ---------------------------------------------------------------- Cash transactions (Expenses feature)
def _validate_refund_target(
    db: Session,
    refund_of_id: Optional[str],
    direction: models.TransactionDirection,
    refund_account: Optional[models.CashAccount] = None,
) -> None:
    if refund_of_id is None:
        return
    if direction != models.TransactionDirection.INCOME:
        raise HTTPException(400, "Only an income can be marked as a refund")
    target = db.get(models.CashTransaction, refund_of_id)
    if not target:
        raise HTTPException(404, "The expense being refunded was not found")
    if target.direction != models.TransactionDirection.EXPENSE:
        raise HTTPException(400, "Only an expense can be refunded")
    if target.transfer_id is not None:
        raise HTTPException(400, "A transfer leg can't be refunded")
    if target.refund_of_id is not None:
        raise HTTPException(400, "A refund can't itself be refunded")

    # A refund is netted against its expense as a raw number, with no FX
    # conversion and regardless of portfolio (see compute_refund_adjustments),
    # so both sides must be the same currency in the same portfolio. Checked
    # only where the link is being created or changed (the caller passes the
    # account then), so an older row that breaks the rule stays editable.
    if refund_account is not None:
        target_account = db.get(models.CashAccount, target.account_id)
        if target_account is None:
            raise HTTPException(404, "The expense being refunded was not found")
        if target_account.portfolio_id != refund_account.portfolio_id:
            raise HTTPException(400, "A refund must be logged in the same portfolio as the expense it refunds")
        if target_account.currency != refund_account.currency:
            raise HTTPException(
                400,
                f"This expense is in {target_account.currency}: log its refund against a "
                f"{target_account.currency} account (refunds aren't currency-converted)",
            )


def _validate_investment_income(
    investment_income_kind: Optional[models.InvestmentIncomeKind],
    direction: models.TransactionDirection,
    refund_of_id: Optional[str],
) -> None:
    if investment_income_kind is None:
        return
    if direction != models.TransactionDirection.INCOME:
        raise HTTPException(400, "Only an income can be marked as dividend/coupon/interest")
    if refund_of_id is not None:
        raise HTTPException(400, "A transaction can't be both a refund and investment income")


@router.post("/cash-accounts/{account_id}/transactions", response_model=schemas.CashTransactionOut)
def create_cash_transaction(
    account_id: str,
    payload: schemas.CashTransactionCreate,
    db: Session = Depends(get_db),
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
):
    cached = _check_idempotency(db, idempotency_key, "create_cash_transaction")
    if cached is not None:
        return cached
    acc = _get_or_404(db, models.CashAccount, account_id, "Cash account")
    if acc.archived_at is not None:
        raise HTTPException(400, "This account has been removed and no longer accepts transactions")
    if acc.category == models.AllocationCategory.PENSION_FUND:
        raise HTTPException(400, "Pension Fund accounts stay hand-updated only -- they don't accept transactions")
    if payload.category_id:
        _get_or_404(db, models.ExpenseCategory, payload.category_id, "Expense category")
    _validate_refund_target(db, payload.refund_of_id, payload.direction, refund_account=acc)
    _validate_investment_income(payload.investment_income_kind, payload.direction, payload.refund_of_id)

    data = payload.model_dump(exclude={"amount", "quantity"})
    data["counterparty_key"] = merchants.normalize(payload.counterparty) or None
    if data["counterparty_key"] and not data.get("category_id"):
        data["category_id"] = merchants.RuleBook(db).category_for(data["counterparty_key"])
    if acc.kind == models.CashAccountKind.VOUCHER:
        if payload.quantity is None:
            raise HTTPException(422, "quantity is required for a voucher account (not amount)")
        if not acc.unit_value:
            # amount would freeze at 0: unit_value is applied at write time only.
            raise HTTPException(400, "Set this account's unit value before logging voucher transactions")
        # Frozen at today's unit_value -- see CashTransaction.amount's
        # docstring for why a later unit_value change shouldn't rewrite this.
        amount = round(payload.quantity * acc.unit_value, 4)
        txn = models.CashTransaction(account_id=account_id, amount=amount, quantity=payload.quantity, **data)
    else:
        if payload.amount is None:
            raise HTTPException(422, "amount is required for this account (not quantity)")
        txn = models.CashTransaction(account_id=account_id, amount=payload.amount, quantity=None, **data)

    db.add(txn)
    replayed = _commit_with_idempotency(db, idempotency_key, "create_cash_transaction")
    if replayed is not None:
        return replayed
    db.refresh(txn)
    out = schemas.CashTransactionOut.model_validate(txn)
    _store_idempotency(db, idempotency_key, "create_cash_transaction", out.model_dump(mode="json"))
    return out


@router.post("/transfers", response_model=schemas.TransferOut)
async def create_transfer(
    payload: schemas.TransferCreate,
    db: Session = Depends(get_db),
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
):
    """
    Moves money between two of the user's own cash accounts -- e.g. topping
    up the Emergency Fund from everyday Cash. Recorded as a linked pair of
    ordinary CashTransaction rows (an EXPENSE on the source, an INCOME on
    the destination, sharing `transfer_id`) so account balances update
    exactly like any other transaction -- but /expenses/summary excludes
    both legs, since moving your own money between your own buckets is
    neither real spending nor real income and shouldn't distort those
    statistics.
    """
    cached = _check_idempotency(db, idempotency_key, "create_transfer")
    if cached is not None:
        return cached
    if payload.from_account_id == payload.to_account_id:
        raise HTTPException(400, "Source and destination must be different accounts")

    from_acc = db.get(models.CashAccount, payload.from_account_id)
    to_acc = db.get(models.CashAccount, payload.to_account_id)
    if not from_acc or not to_acc:
        raise HTTPException(404, "Cash account not found")

    for acc, role in [(from_acc, "source"), (to_acc, "destination")]:
        if acc.archived_at is not None:
            raise HTTPException(400, f"The {role} account has been removed and no longer accepts transfers")
        if acc.category == models.AllocationCategory.PENSION_FUND:
            raise HTTPException(400, "Pension Fund accounts stay hand-updated only -- they don't accept transfers")
        if acc.kind == models.CashAccountKind.VOUCHER:
            raise HTTPException(400, "Voucher accounts don't support transfers")

    if from_acc.currency == to_acc.currency:
        received = payload.amount
    else:
        fx = await price_client.fx_rate_at(from_acc.currency, to_acc.currency, payload.entry_date)
        received = round(payload.amount * fx, 4)

    transfer_id = models.gen_id()
    from_leg = models.CashTransaction(
        account_id=from_acc.id,
        entry_date=payload.entry_date,
        direction=models.TransactionDirection.EXPENSE,
        amount=payload.amount,
        note=payload.note,
        transfer_id=transfer_id,
    )
    to_leg = models.CashTransaction(
        account_id=to_acc.id,
        entry_date=payload.entry_date,
        direction=models.TransactionDirection.INCOME,
        amount=received,
        note=payload.note,
        transfer_id=transfer_id,
    )
    db.add(from_leg)
    db.add(to_leg)
    replayed = _commit_with_idempotency(db, idempotency_key, "create_transfer")
    if replayed is not None:
        return replayed
    db.refresh(from_leg)
    db.refresh(to_leg)
    out = schemas.TransferOut(transfer_id=transfer_id, from_leg=from_leg, to_leg=to_leg)
    _store_idempotency(db, idempotency_key, "create_transfer", out.model_dump(mode="json"))
    return out


@router.get("/cash-accounts/{account_id}/transactions", response_model=List[schemas.CashTransactionOut])
def list_cash_account_transactions(
    account_id: str,
    limit: Optional[int] = None,
    offset: int = 0,
    uncategorized: bool = False,
    filters: schemas.TransactionFilters = Depends(),
    db: Session = Depends(get_db),
):
    q = _transactions_query(db, None, account_id, uncategorized, filters)
    return _paginate(q, limit, offset).all()


def _apply_filters(q, f: "schemas.TransactionFilters"):
    """The search/filter parameters both transaction lists (and the CSV
    export) accept. Every one is optional; together they narrow (AND)."""
    T = models.CashTransaction
    if f.q and f.q.strip():
        # A literal search: % and _ typed by the user mean themselves.
        term = f.q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = f"%{term}%"
        q = q.filter(or_(T.note.ilike(pattern, escape="\\"), T.counterparty.ilike(pattern, escape="\\")))
    if f.category_id:
        q = q.filter(T.category_id == f.category_id)
    if f.from_date:
        q = q.filter(T.entry_date >= f.from_date)
    if f.to_date:
        q = q.filter(T.entry_date <= f.to_date)
    if f.min_amount is not None:
        q = q.filter(T.amount >= f.min_amount)
    if f.max_amount is not None:
        q = q.filter(T.amount <= f.max_amount)
    if f.direction:
        q = q.filter(T.direction == f.direction)
    return q


def _only_uncategorized(q):
    """Transactions still waiting for a category: not transfer legs or
    refunds, which are deliberately never categorized."""
    return q.filter(
        models.CashTransaction.category_id.is_(None),
        models.CashTransaction.transfer_id.is_(None),
        models.CashTransaction.refund_of_id.is_(None),
    )


def _transactions_query(db: Session, portfolio_id, account_id, uncategorized, filters):
    q = db.query(models.CashTransaction)
    if portfolio_id:
        q = q.join(models.CashAccount, models.CashTransaction.account_id == models.CashAccount.id).filter(
            models.CashAccount.portfolio_id == portfolio_id
        )
    if account_id:
        q = q.filter(models.CashTransaction.account_id == account_id)
    if uncategorized:
        q = _only_uncategorized(q)
    q = _apply_filters(q, filters)
    return q.order_by(models.CashTransaction.entry_date.desc(), models.CashTransaction.created_at.desc())


@router.get("/transactions", response_model=List[schemas.CashTransactionOut])
def list_transactions(
    portfolio_id: Optional[str] = None,
    account_id: Optional[str] = None,
    limit: Optional[int] = None,
    offset: int = 0,
    uncategorized: bool = False,
    filters: schemas.TransactionFilters = Depends(),
    db: Session = Depends(get_db),
):
    """Flat, filterable transaction list across accounts/portfolios -- backs the Expenses history/report views."""
    q = _transactions_query(db, portfolio_id, account_id, uncategorized, filters)
    return _paginate(q, limit, offset).all()


@router.get("/transactions/export.csv")
def export_transactions_csv(
    portfolio_id: Optional[str] = None,
    account_id: Optional[str] = None,
    uncategorized: bool = False,
    filters: schemas.TransactionFilters = Depends(),
    db: Session = Depends(get_db),
):
    """
    The same list as GET /transactions, with the same filters, as a CSV file
    -- for a spreadsheet, or whoever does your taxes. Amounts are in each
    account's own currency (named in its own column), never converted:
    an export should say what actually happened.
    """
    q = _transactions_query(db, portfolio_id, account_id, uncategorized, filters)
    accounts: dict[str, models.CashAccount] = {}
    portfolios: dict[str, Optional[models.Portfolio]] = {}
    categories: dict[str, Optional[models.ExpenseCategory]] = {}
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["date", "portfolio", "account", "type", "amount", "currency", "quantity",
                "category", "counterparty", "note", "transfer_id", "refund_of_id", "id"])
    for t in q.all():
        acc = accounts.setdefault(t.account_id, db.get(models.CashAccount, t.account_id))
        if acc.portfolio_id not in portfolios:
            portfolios[acc.portfolio_id] = db.get(models.Portfolio, acc.portfolio_id)
        portfolio = portfolios[acc.portfolio_id]
        category = None
        if t.category_id:
            if t.category_id not in categories:
                categories[t.category_id] = db.get(models.ExpenseCategory, t.category_id)
            category = categories[t.category_id]
        kind = (
            "TRANSFER" if t.transfer_id
            else "REFUND" if t.refund_of_id
            else t.investment_income_kind.value if t.investment_income_kind
            else t.direction.value
        )
        w.writerow([
            t.entry_date.isoformat(), portfolio.name if portfolio else "", acc.name, kind,
            # Signed, so a column sum is the net movement.
            f"{(t.amount if t.direction == models.TransactionDirection.INCOME else -t.amount):.2f}",
            acc.currency, "" if t.quantity is None else t.quantity,
            category.name if category else "", t.counterparty or "", t.note or "",
            t.transfer_id or "", t.refund_of_id or "", t.id,
        ])
    stamp = date.today().isoformat()
    return Response(
        # A BOM so Excel opens accented names (and the euro sign) correctly.
        content="\ufeff" + buf.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="transactions-{stamp}.csv"'},
    )


@router.post("/cash-transactions/bulk-categorize", response_model=schemas.BulkCategorizeResult)
def bulk_categorize(payload: schemas.BulkCategorize, db: Session = Depends(get_db)):
    """
    Gives several transactions the same category (or clears it, with
    category_id null) in one go. All or nothing: an unknown id, or a transfer
    leg -- which is never categorized -- refuses the whole request, so a
    partial result never has to be worked out from what's on screen.
    """
    if payload.category_id:
        _get_or_404(db, models.ExpenseCategory, payload.category_id, "Expense category")
    ids = list(dict.fromkeys(payload.transaction_ids))
    txns = db.query(models.CashTransaction).filter(models.CashTransaction.id.in_(ids)).all()
    if len(txns) != len(ids):
        raise HTTPException(404, f"{len(ids) - len(txns)} of the selected transactions no longer exist -- reload and try again")
    if any(t.transfer_id is not None for t in txns):
        raise HTTPException(400, "Transfers can't be categorized -- leave them out of the selection")
    for t in txns:
        t.category_id = payload.category_id
    db.commit()
    return schemas.BulkCategorizeResult(updated=len(txns))


@router.post("/cash-transactions/{transaction_id}/convert-to-transfer", response_model=schemas.TransferOut)
async def convert_to_transfer(
    transaction_id: str, payload: schemas.ConvertToTransfer, db: Session = Depends(get_db)
):
    """
    Turns an existing income or expense into one leg of a transfer with
    another of your own accounts, creating only the missing leg there.

    For money moved between your own accounts when only one side of it is
    already recorded -- typically bank-sync capturing a top-up on the one
    linked account. Logging the other side as a fresh transfer would count
    the linked account's side twice; logging it as an ordinary expense would
    count it as spending. Here an INCOME came *from* the other account, an
    EXPENSE went *to* it; both legs then share `transfer_id` and leave the
    income/expense statistics, exactly like a transfer made from scratch.
    """
    txn = _get_or_404(db, models.CashTransaction, transaction_id, "Transaction")
    if txn.transfer_id is not None:
        raise HTTPException(400, "This is already part of a transfer")
    if txn.refund_of_id is not None:
        raise HTTPException(400, "A refund can't become a transfer -- remove the refund link first")
    if txn.investment_income_kind is not None:
        raise HTTPException(400, "A dividend/coupon/interest payment can't become a transfer")
    if db.query(models.CashTransaction.id).filter(models.CashTransaction.refund_of_id == txn.id).first():
        raise HTTPException(400, "This expense has refunds logged against it, so it has to stay an ordinary expense")
    if payload.other_account_id == txn.account_id:
        raise HTTPException(400, "Pick a different account from the one this transaction is on")

    this_acc = db.get(models.CashAccount, txn.account_id)
    other_acc = _get_or_404(db, models.CashAccount, payload.other_account_id, "Cash account")
    if other_acc.archived_at is not None:
        raise HTTPException(400, "The other account has been removed and no longer accepts transfers")
    for acc, role in [(this_acc, "this transaction's"), (other_acc, "the other")]:
        if acc.category == models.AllocationCategory.PENSION_FUND:
            raise HTTPException(400, "Pension Fund accounts stay hand-updated only -- they don't accept transfers")
        if acc.kind == models.CashAccountKind.VOUCHER:
            raise HTTPException(400, f"Voucher accounts don't support transfers ({role} account is one)")

    # The other leg's amount in the other account's own currency, at the
    # transaction's own date -- the same historical/live split create_transfer
    # uses.
    if this_acc.currency == other_acc.currency:
        other_amount = txn.amount
    else:
        fx = await price_client.fx_rate_at(this_acc.currency, other_acc.currency, txn.entry_date)
        other_amount = round(txn.amount * fx, 4)

    transfer_id = models.gen_id()
    other_leg = models.CashTransaction(
        account_id=other_acc.id,
        entry_date=txn.entry_date,
        direction=(
            models.TransactionDirection.EXPENSE
            if txn.direction == models.TransactionDirection.INCOME
            else models.TransactionDirection.INCOME
        ),
        amount=other_amount,
        note=txn.note,
        transfer_id=transfer_id,
    )
    txn.transfer_id = transfer_id
    # A transfer leg is never categorized (and can't be edited to fix one).
    txn.category_id = None
    db.add(other_leg)
    db.commit()
    db.refresh(txn)
    db.refresh(other_leg)
    if txn.direction == models.TransactionDirection.EXPENSE:
        from_leg, to_leg = txn, other_leg
    else:
        from_leg, to_leg = other_leg, txn
    return schemas.TransferOut(transfer_id=transfer_id, from_leg=from_leg, to_leg=to_leg)


@router.get("/cash-transactions/{transaction_id}", response_model=schemas.CashTransactionOut)
def get_cash_transaction(transaction_id: str, db: Session = Depends(get_db)):
    """One transaction by id. bank-sync reads a card payment it captured
    while still pending back through this before correcting it once the bank
    books it, so a category or amount you already fixed by hand is left
    alone instead of being overwritten."""
    return _get_or_404(db, models.CashTransaction, transaction_id, "Transaction")


@router.patch("/cash-transactions/{transaction_id}", response_model=schemas.CashTransactionOut)
def update_cash_transaction(transaction_id: str, payload: schemas.CashTransactionUpdate, db: Session = Depends(get_db)):
    txn = _get_or_404(db, models.CashTransaction, transaction_id, "Transaction")
    if txn.transfer_id is not None:
        raise HTTPException(400, "This is one leg of a transfer -- delete and re-create the transfer instead of editing it")
    data = payload.model_dump(exclude_unset=True)
    if data.get("category_id"):
        _get_or_404(db, models.ExpenseCategory, data["category_id"], "Expense category")

    # Re-validate against the transaction's *final* state, not just the
    # fields the payload happens to touch -- changing only `direction` (say,
    # INCOME -> EXPENSE) while leaving an existing refund_of_id untouched
    # would otherwise leave a now-EXPENSE row still linked as a refund,
    # which compute_refund_adjustments() would then double-count.
    final_refund_of_id = data.get("refund_of_id", txn.refund_of_id)
    final_direction = data.get("direction", txn.direction)
    final_investment_income_kind = data.get("investment_income_kind", txn.investment_income_kind)
    if final_refund_of_id == transaction_id:
        raise HTTPException(400, "A transaction can't refund itself")

    # The rules _validate_refund_target enforces on a refund's *target* must
    # hold from the target's side too: an expense other refunds point at
    # stays an expense and can't itself become a refund, or those refunds
    # would be netted against a row /expenses/summary no longer counts.
    if final_direction != models.TransactionDirection.EXPENSE or final_refund_of_id is not None:
        has_refunds = (
            db.query(models.CashTransaction.id)
            .filter(models.CashTransaction.refund_of_id == transaction_id)
            .first()
        )
        if has_refunds:
            raise HTTPException(
                400,
                "This expense has refunds logged against it, so it has to stay an ordinary expense. "
                "Remove those refunds first if you need to change it.",
            )

    acc = db.get(models.CashAccount, txn.account_id)
    # The full same-portfolio/same-currency check applies to a link being set
    # or changed by this request; an untouched one is only re-checked for the
    # direction/target rules, so an older row stays editable.
    _validate_refund_target(
        db,
        final_refund_of_id,
        final_direction,
        refund_account=acc if "refund_of_id" in data else None,
    )
    _validate_investment_income(final_investment_income_kind, final_direction, final_refund_of_id)

    if acc.kind == models.CashAccountKind.VOUCHER:
        # On a voucher account `amount` is derived (quantity * unit_value)
        # and frozen at write time, so it can't be edited directly.
        if "amount" in data:
            raise HTTPException(
                400, "On a voucher account edit `quantity` -- `amount` is derived from it and can't be set directly"
            )
        if "quantity" in data:
            if not acc.unit_value:
                raise HTTPException(400, "Set this account's unit value before editing voucher transactions")
            # Re-freeze the amount using *today's* unit_value, same as creating
            # a new transaction would -- editing a quantity is treated as a
            # fresh entry, not a correction that should preserve an old rate.
            data["amount"] = round(data["quantity"] * acc.unit_value, 4)
    else:
        data.pop("quantity", None)  # ignore quantity edits on a CURRENCY account

    if "counterparty" in data:
        data["counterparty_key"] = merchants.normalize(data["counterparty"]) or None
        # Setting the counterparty of an uncategorized transaction categorizes
        # it the same way creating it with that counterparty would have.
        if data["counterparty_key"] and "category_id" not in data and txn.category_id is None:
            category_id = merchants.RuleBook(db).category_for(data["counterparty_key"])
            if category_id:
                data["category_id"] = category_id

    for k, v in data.items():
        setattr(txn, k, v)
    db.commit()
    db.refresh(txn)
    return txn


@router.delete("/cash-transactions/{transaction_id}", status_code=204)
def delete_cash_transaction(transaction_id: str, db: Session = Depends(get_db)):
    txn = _get_or_404(db, models.CashTransaction, transaction_id, "Transaction")
    if txn.transfer_id is not None:
        # Delete both legs together -- leaving one side behind would look
        # like a real, one-sided expense or income that never happened.
        db.query(models.CashTransaction).filter(models.CashTransaction.transfer_id == txn.transfer_id).delete()
    else:
        # Refunds against this expense are un-linked, so they become
        # ordinary, full-value income instead of vanishing from the reports.
        db.query(models.CashTransaction).filter(models.CashTransaction.refund_of_id == transaction_id).update(
            {"refund_of_id": None}
        )
        db.delete(txn)
    db.commit()


def compute_refund_adjustments(db: Session) -> tuple[dict[str, float], dict[str, float]]:
    """
    Refunds (see CashTransaction.refund_of_id) don't rewrite the expense
    they offset -- they're ordinary income rows, dated whenever the money
    actually came back. This is where that gets reconciled for reporting:

    - effective_amounts[expense_id]: the expense's own amount minus every
      refund against it (in chronological order, so several partial
      refunds are applied correctly), floored at 0. This is what
      /expenses/summary should count as "spent" for that expense, however
      long ago it happened -- not its original, un-refunded amount.
    - excess_amounts[refund_id]: how much of a given refund went *beyond*
      what was left owed on its expense. Only this leftover portion should
      ever count as real income -- the rest already shows up as a smaller
      expense via effective_amounts, so counting it again as income too
      would double-count the same money.

    Computed globally (not date- or portfolio-filtered) since a refund
    outside a report's window can still reduce an expense inside it, and
    vice versa.
    """
    refunds = (
        db.query(models.CashTransaction)
        .filter(models.CashTransaction.refund_of_id.isnot(None))
        .order_by(models.CashTransaction.entry_date, models.CashTransaction.created_at)
        .all()
    )
    by_expense: dict[str, list[models.CashTransaction]] = {}
    for r in refunds:
        by_expense.setdefault(r.refund_of_id, []).append(r)

    effective_amounts: dict[str, float] = {}
    excess_amounts: dict[str, float] = {}
    for expense_id, rs in by_expense.items():
        expense = db.get(models.CashTransaction, expense_id)
        if not expense:
            # The expense this points at is gone (only reachable for a row
            # edited straight in the database: every delete path un-links
            # refunds first). With nothing left to absorb it, all of it is
            # ordinary income.
            for r in rs:
                excess_amounts[r.id] = r.amount
            continue
        remaining = expense.amount
        for r in rs:
            applied = min(r.amount, remaining)
            excess_amounts[r.id] = round(r.amount - applied, 4)
            remaining -= applied
        effective_amounts[expense_id] = round(remaining, 4)
    return effective_amounts, excess_amounts


@router.get("/expenses/summary", response_model=schemas.ExpenseSummary)
async def expenses_summary(
    from_date: date,
    to_date: date,
    portfolio_id: Optional[str] = None,
    currency: str = "EUR",
    db: Session = Depends(get_db),
):
    """
    Total income/expense and a per-category breakdown over a date range, all
    converted to `currency` using each transaction's own account currency and
    that day's historical FX rate -- the same approach used for historical
    net worth valuation, since accounts (and therefore their transactions)
    aren't necessarily all in the same currency. Internal transfers (see
    POST /transfers) are excluded entirely -- moving your own money between
    your own accounts isn't spending or income, and counting it as either
    would distort these very statistics. Refunded expenses count at their
    reduced, post-refund amount (see compute_refund_adjustments); a refund
    itself only counts as income for whatever portion exceeded its expense.
    """
    found = await reports.flows(db, from_date, to_date, portfolio_id, currency, compute_refund_adjustments(db))
    total_income = sum(f.amount for f in found if f.income)
    total_expense = sum(f.amount for f in found if not f.income)
    name_of = _category_namer(db)
    return schemas.ExpenseSummary(
        from_date=from_date,
        to_date=to_date,
        currency=currency,
        total_income=total_income,
        total_expense=total_expense,
        net=total_income - total_expense,
        by_category=reports.by_category(found, income=False, name_of=name_of),
        # Income has categories too (a salary, a merchant's refund, money
        # from a friend) -- reported the same way, separately.
        income_by_category=reports.by_category(found, income=True, name_of=name_of),
    )


def _category_namer(db: Session):
    names: dict[Optional[str], str] = {}

    def name_of(category_id: Optional[str]) -> str:
        if category_id is None:
            return "Uncategorized"
        if category_id not in names:
            cat = db.get(models.ExpenseCategory, category_id)
            names[category_id] = cat.name if cat else "Unknown"
        return names[category_id]
    return name_of


@router.get("/expenses/monthly", response_model=List[schemas.MonthlyFlow])
async def expenses_monthly(
    months: int = Query(12, ge=1, le=120),
    portfolio_id: Optional[str] = None,
    currency: str = "EUR",
    db: Session = Depends(get_db),
):
    """
    Income, spending, what was left and the savings rate for each of the
    last `months` calendar months, the current one included (so far). Counted
    exactly like /expenses/summary.
    """
    last = reports.month_start(date.today())
    first = reports.add_months(last, -(months - 1))
    found = await reports.flows(db, first, date.today(), portfolio_id, currency, compute_refund_adjustments(db))
    return reports.monthly(found, first, last)


# ---------------------------------------------------------------- Recurring payments
@router.get("/recurring", response_model=schemas.RecurringReport)
async def recurring_payments(
    portfolio_id: Optional[str] = None,
    currency: str = "EUR",
    db: Session = Depends(get_db),
):
    """
    Subscriptions and other recurring payments, detected from the last ~13
    months of spending (see reports.detect_recurring): grouped by merchant --
    the counterparty a bank sent, or for one logged by hand its note -- with
    the cadence, what it costs per month, and any recent price change.
    `monthly_total` adds up the active ones.
    """
    today = date.today()
    found = await reports.flows(
        db, today - timedelta(days=400), today, portfolio_id, currency, compute_refund_adjustments(db)
    )
    expenses = []
    for f in found:
        if f.income:
            continue
        key = f.txn.counterparty_key or merchants.normalize(f.txn.note)
        name = f.txn.counterparty or f.txn.note or ""
        expenses.append((key, name, f.txn.entry_date, f.amount, f.txn.category_id))
    items = reports.detect_recurring(expenses, today)
    return schemas.RecurringReport(
        currency=currency,
        monthly_total=round(sum(i["monthly_cost"] for i in items if i["active"]), 2),
        items=items,
    )
