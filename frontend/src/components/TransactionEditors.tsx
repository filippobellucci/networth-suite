import { useState } from "react";
import { api } from "../api/client";
import type { CashAccount, CashTransaction, ExpenseCategory, InvestmentIncomeKind } from "../types";
import { formatMoneyPrecise, parseLocaleFloat, todayISO } from "../lib/format";
import { errorText } from "../lib/errors";
import { canMarkInvestmentIncome } from "../lib/investmentIncome";

/**
 * Edits an existing transaction: date, amount (quantity on a voucher
 * account), category, income type (dividend/coupon/interest, income only)
 * and note. Only the fields actually changed are sent, so e.g. fixing a note
 * never re-sends -- and re-validates -- an amount nobody touched. Transfer
 * legs never get here: the server refuses to edit one leg of a pair on its
 * own.
 */
export function EditTransactionForm({
  txn,
  account,
  categories,
  onDone,
  onCancel,
}: {
  txn: CashTransaction;
  account: CashAccount;
  categories: ExpenseCategory[];
  onDone: () => void;
  onCancel: () => void;
}) {
  const isVoucher = account.kind === "VOUCHER";
  const isRefund = !!txn.refund_of_id;
  const showIncomeKind = canMarkInvestmentIncome(txn.direction, isRefund);
  const initialAmount = String(isVoucher ? txn.quantity ?? "" : txn.amount);
  const initialIncomeKind = txn.investment_income_kind ?? "";
  const [entryDate, setEntryDate] = useState(txn.entry_date);
  const [amount, setAmount] = useState(initialAmount);
  const [categoryId, setCategoryId] = useState(txn.category_id ?? "");
  const [investmentIncomeKind, setInvestmentIncomeKind] = useState<"" | InvestmentIncomeKind>(initialIncomeKind);
  const [note, setNote] = useState(txn.note ?? "");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const changes: Parameters<typeof api.updateCashTransaction>[1] = {};
    if (entryDate !== txn.entry_date) changes.entry_date = entryDate;
    if (amount.trim() !== initialAmount) {
      const num = parseLocaleFloat(amount);
      if (isNaN(num) || num <= 0) {
        setError(isVoucher ? "Enter a positive quantity." : "Enter a positive amount.");
        return;
      }
      if (isVoucher) changes.quantity = num;
      else changes.amount = num;
    }
    if (!isRefund && (categoryId || null) !== (txn.category_id ?? null)) changes.category_id = categoryId || null;
    if (showIncomeKind && (investmentIncomeKind || null) !== (initialIncomeKind || null))
      changes.investment_income_kind = investmentIncomeKind || null;
    if (note.trim() !== (txn.note ?? "")) changes.note = note.trim() || null;
    if (Object.keys(changes).length === 0) {
      onCancel();
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await api.updateCashTransaction(txn.id, changes);
      onDone();
    } catch (e) {
      setError(errorText(e));
    } finally {
      setSaving(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="card p-5 space-y-4" aria-label="Edit transaction">
      <div className="flex items-baseline justify-between gap-3 flex-wrap">
        <h3 className="font-display text-base">
          Edit {isRefund ? "refund" : txn.direction === "INCOME" ? "income" : "expense"}
        </h3>
        {txn.counterparty && <span className="text-muted text-xs">{txn.counterparty}</span>}
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <div>
          <label className="field-label">
            {isVoucher ? "Quantity" : `Amount (${account.currency})`}
          </label>
          <input className="input w-full" value={amount} onChange={(e) => setAmount(e.target.value)} inputMode="decimal" />
        </div>
        <div>
          <label className="field-label">Date</label>
          <input
            type="date"
            className="input w-full"
            value={entryDate}
            onChange={(e) => setEntryDate(e.target.value)}
            max={todayISO()}
          />
        </div>
        {!isRefund && (
          <div>
            <label className="field-label">Category</label>
            <select className="input w-full" value={categoryId} onChange={(e) => setCategoryId(e.target.value)}>
              <option value="">None</option>
              {categories.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </select>
          </div>
        )}
        {showIncomeKind && (
          <div>
            <label className="field-label">Income type</label>
            <select
              className="input w-full"
              value={investmentIncomeKind}
              onChange={(e) => setInvestmentIncomeKind(e.target.value as "" | InvestmentIncomeKind)}
            >
              <option value="">Not investment income</option>
              <option value="DIVIDEND">Dividend</option>
              <option value="COUPON">Coupon</option>
              <option value="INTEREST">Interest</option>
            </select>
          </div>
        )}
        <div>
          <label className="field-label">Note</label>
          <input className="input w-full" value={note} onChange={(e) => setNote(e.target.value)} />
        </div>
      </div>
      {error && <p className="text-loss text-sm">{error}</p>}
      <div className="flex gap-3">
        <button className="btn-primary" disabled={saving}>
          {saving ? "Saving…" : "Save changes"}
        </button>
        <button type="button" className="btn-ghost" onClick={onCancel}>
          Cancel
        </button>
      </div>
    </form>
  );
}

/**
 * Turns a one-sided income/expense into a transfer with another of your own
 * accounts -- the bank-synced top-up whose other side lives on an account
 * that isn't linked. Only the missing leg is created.
 */
export function ConvertToTransferForm({
  txn,
  account,
  candidates,
  onDone,
  onCancel,
}: {
  txn: CashTransaction;
  account: CashAccount;
  /** Accounts the other leg may go on: same portfolio, not voucher, not this one. */
  candidates: CashAccount[];
  onDone: () => void;
  onCancel: () => void;
}) {
  const [otherId, setOtherId] = useState(candidates[0]?.id ?? "");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const incoming = txn.direction === "INCOME";
  const other = candidates.find((a) => a.id === otherId);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!otherId) return;
    setSaving(true);
    setError(null);
    try {
      await api.convertToTransfer(txn.id, otherId);
      onDone();
    } catch (e) {
      setError(errorText(e));
    } finally {
      setSaving(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="card p-5 space-y-4" aria-label="Convert to transfer">
      <h3 className="font-display text-base">Mark as a transfer between your accounts</h3>
      <p className="text-muted text-sm">
        {incoming ? "+" : "−"}
        {formatMoneyPrecise(txn.amount, account.currency)} on {account.name}
        {txn.counterparty ? ` (${txn.counterparty})` : ""}. The matching{" "}
        {incoming ? "outgoing" : "incoming"} side is added to the account below, and both stop counting as{" "}
        {incoming ? "income" : "spending"}.
      </p>
      {candidates.length === 0 ? (
        <p className="text-sm text-muted">No other account in this portfolio can take part in a transfer.</p>
      ) : (
        <div>
          <label className="field-label">
            {incoming ? "Came from" : "Went to"}
          </label>
          <select className="input w-full" value={otherId} onChange={(e) => setOtherId(e.target.value)}>
            {candidates.map((a) => (
              <option key={a.id} value={a.id}>
                {a.name} ({a.currency})
              </option>
            ))}
          </select>
          {other && other.currency !== account.currency && (
            <p className="text-xs text-muted mt-1">Converted to {other.currency} at that day's rate.</p>
          )}
        </div>
      )}
      {error && <p className="text-loss text-sm">{error}</p>}
      <div className="flex gap-3">
        <button className="btn-primary" disabled={saving || !otherId}>
          {saving ? "Saving…" : "⇄ Make it a transfer"}
        </button>
        <button type="button" className="btn-ghost" onClick={onCancel}>
          Cancel
        </button>
      </div>
    </form>
  );
}
