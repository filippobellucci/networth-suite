import { useEffect, useMemo, useState } from "react";
import { api } from "../api/client";
import type {
  CashAccount,
  ExpenseCategory,
  CashTransaction,
  InvestmentIncomeKind,
} from "../types";
import { formatMoneyPrecise, formatDate, todayISO, parseLocaleFloat } from "../lib/format";
import SegmentedControl from "./SegmentedControl";
import { refundCandidates } from "../lib/refunds";
import { errorText } from "../lib/errors";

type Kind = "INCOME" | "EXPENSE" | "TRANSFER" | "REFUND";

/**
 * Logs a new income, expense, transfer or refund against a cash account of
 * the selected portfolio.
 * Owns every field of the entry form; tells the parent (via `onLogged`)
 * only once a transaction has actually been created, so it can refresh the
 * recent list and the refund candidates derived from it.
 */
export default function TransactionLogForm({
  accounts,
  accountId,
  onAccountIdChange,
  transferAccounts,
  allAccounts,
  portfolioTransactions,
  categories,
  selectedAccount,
  onLogged,
}: {
  accounts: CashAccount[];
  accountId: string;
  onAccountIdChange: (id: string) => void;
  /** Accounts a transfer leg may use -- vouchers don't support transfers. */
  transferAccounts: CashAccount[];
  /** Same portfolio, archived accounts included -- see the refund picker below. */
  allAccounts: CashAccount[];
  portfolioTransactions: CashTransaction[];
  categories: ExpenseCategory[];
  selectedAccount: CashAccount | undefined;
  onLogged: () => void;
}) {
  const [toAccountId, setToAccountId] = useState("");
  const [refundOfId, setRefundOfId] = useState("");
  const [kind, setKind] = useState<Kind>("EXPENSE");
  const [amount, setAmount] = useState("");
  const [categoryId, setCategoryId] = useState("");
  const [investmentIncomeKind, setInvestmentIncomeKind] = useState<"" | InvestmentIncomeKind>("");
  const [entryDate, setEntryDate] = useState(todayISO());
  const [note, setNote] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (kind !== "TRANSFER") return;
    setToAccountId((current) => {
      if (current && current !== accountId && transferAccounts.some((a) => a.id === current)) return current;
      return transferAccounts.find((a) => a.id !== accountId)?.id ?? "";
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [kind, accountId, accounts]);

  // Recomputed only when the ledger changes, not on every keystroke.
  const candidates = useMemo(() => refundCandidates(portfolioTransactions, allAccounts), [portfolioTransactions, allAccounts]);

  const toAccount = accounts.find((a) => a.id === toAccountId);
  // The expense currently picked in the refund dropdown -- looked up once
  // here rather than re-found inline everywhere the form describes it.
  const pickedRefund = candidates.find((c) => c.expense.id === refundOfId);
  const refundCurrency = pickedRefund?.accountCurrency ?? selectedAccount?.currency;
  const isVoucher = kind !== "TRANSFER" && kind !== "REFUND" && selectedAccount?.kind === "VOUCHER";
  const isTransfer = kind === "TRANSFER";
  const isRefund = kind === "REFUND";
  // The server refuses a refund on an account in another currency than the
  // expense's (refunds aren't converted), so once an expense is picked only
  // accounts in its currency are offered.
  const pickableAccounts =
    isRefund && pickedRefund ? accounts.filter((a) => a.currency === pickedRefund.accountCurrency) : accounts;

  function pickRefund(expenseId: string) {
    setRefundOfId(expenseId);
    const currency = candidates.find((c) => c.expense.id === expenseId)?.accountCurrency;
    if (currency && selectedAccount?.currency !== currency) {
      const match = accounts.find((a) => a.currency === currency);
      if (match) onAccountIdChange(match.id);
    }
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const num = parseLocaleFloat(amount);
    if (isTransfer) {
      if (!accountId || !toAccountId || accountId === toAccountId || isNaN(num) || num <= 0) {
        setError("Pick two different accounts and enter a positive amount.");
        return;
      }
    } else if (isRefund) {
      if (!accountId || !refundOfId || isNaN(num) || num <= 0) {
        setError("Pick an account, the expense being refunded, and enter a positive amount.");
        return;
      }
      if (pickedRefund && selectedAccount?.currency !== pickedRefund.accountCurrency) {
        setError(`This expense is in ${pickedRefund.accountCurrency}: its refund needs an active ${pickedRefund.accountCurrency} account.`);
        return;
      }
    } else if (!accountId || isNaN(num) || num <= 0) {
      setError(isVoucher ? "Pick an account and enter a positive quantity." : "Pick an account and enter a positive amount.");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      if (isTransfer) {
        await api.createTransfer({
          from_account_id: accountId,
          to_account_id: toAccountId,
          entry_date: entryDate,
          amount: num,
          note: note.trim() || undefined,
        });
      } else if (isRefund) {
        await api.createCashTransaction(accountId, {
          entry_date: entryDate,
          direction: "INCOME",
          amount: num,
          refund_of_id: refundOfId,
          note: note.trim() || undefined,
        });
      } else {
        await api.createCashTransaction(accountId, {
          entry_date: entryDate,
          direction: kind,
          ...(isVoucher ? { quantity: num } : { amount: num }),
          category_id: categoryId || undefined,
          note: note.trim() || undefined,
          ...(kind === "INCOME" ? { investment_income_kind: investmentIncomeKind || undefined } : {}),
        });
      }
      // Keep portfolio/account/kind/date so a run of same-day entries (e.g.
      // logging today's receipts one by one) doesn't require re-selecting
      // them every time -- only amount/category/note (and the picked
      // expense, for a refund) reset.
      setAmount("");
      setCategoryId("");
      setNote("");
      setRefundOfId("");
      setInvestmentIncomeKind("");
      onLogged();
    } catch (e) {
      setError(errorText(e));
    } finally {
      setSaving(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="card p-6 space-y-4" aria-label="Log a transaction">
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <div>
          <label className="field-label">
            {isTransfer ? "From account" : "Account"}
          </label>
          <select
            className="input w-full"
            aria-label={isTransfer ? "From account" : "Account"}
            value={accountId}
            onChange={(e) => onAccountIdChange(e.target.value)}
          >
            {pickableAccounts.length === 0 && (
              <option value="">
                {isRefund && pickedRefund
                  ? `No active ${pickedRefund.accountCurrency} account in this portfolio`
                  : "No eligible cash accounts in this portfolio"}
              </option>
            )}
            {pickableAccounts.map((a) => (
              <option key={a.id} value={a.id}>
                {a.name} ({a.currency})
              </option>
            ))}
          </select>
        </div>
      </div>

      <div>
        <label className="text-xs uppercase tracking-wide text-muted block mb-2">Type</label>
        <SegmentedControl
          options={[
            { value: "EXPENSE", label: "Expense" },
            { value: "INCOME", label: "Income" },
            { value: "TRANSFER", label: "Transfer" },
            { value: "REFUND", label: "Refund" },
          ]}
          value={kind}
          onChange={setKind}
        />
      </div>

      {isTransfer && (
        <div>
          <label className="field-label">To account</label>
          <select className="input w-full" value={toAccountId} onChange={(e) => setToAccountId(e.target.value)}>
            {transferAccounts
              .filter((a) => a.id !== accountId)
              .map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name} ({a.currency})
                </option>
              ))}
          </select>
        </div>
      )}

      {isRefund && (
        <div>
          <label className="field-label">Expense being refunded</label>
          <select
            className="input w-full"
            aria-label="Expense being refunded"
            value={refundOfId}
            onChange={(e) => pickRefund(e.target.value)}
          >
            <option value="">Select an expense…</option>
            {candidates.map(({ expense, remaining, accountName, accountCurrency }) => (
              <option key={expense.id} value={expense.id}>
                {formatDate(expense.entry_date)} — {expense.note || "(no note)"} — {accountName} —{" "}
                {remaining > 0
                  ? `${formatMoneyPrecise(remaining, accountCurrency)} left of ${formatMoneyPrecise(expense.amount, accountCurrency)}`
                  : "fully refunded"}
              </option>
            ))}
          </select>
          {candidates.length === 0 && (
            <p className="text-xs text-muted mt-1">No expenses logged in this portfolio yet.</p>
          )}
          {pickedRefund && (
            <p className="text-xs text-muted mt-1">
              This expense is in {pickedRefund.accountCurrency}: its refund is logged in{" "}
              {pickedRefund.accountCurrency}, on an account in that currency (refunds aren't
              currency-converted), so only those accounts are offered above.
            </p>
          )}
        </div>
      )}

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <div>
          <label className="field-label">
            {isVoucher
              ? "Quantity"
              : isRefund
                ? // The backend compares this amount directly against the
                  // original expense's own amount with no FX conversion, and
                  // the receiving account is always in that same currency.
                  `Amount received ${refundCurrency ? `(${refundCurrency})` : ""}`
                : `Amount ${selectedAccount ? `(${selectedAccount.currency})` : ""}`}
          </label>
          <input
            className="input w-full"
            value={amount}
            onChange={(e) => setAmount(e.target.value)}
            placeholder={isVoucher ? "e.g. 2" : "0.00"}
            inputMode="decimal"
            autoFocus
          />
          {isVoucher && selectedAccount && !isNaN(parseLocaleFloat(amount)) && parseLocaleFloat(amount) > 0 && (
            <p className="text-xs text-muted mt-1">
              = {formatMoneyPrecise(parseLocaleFloat(amount) * (selectedAccount.unit_value ?? 0), selectedAccount.currency)}
            </p>
          )}
          {isTransfer && selectedAccount && toAccount && selectedAccount.currency !== toAccount.currency && (
            <p className="text-xs text-muted mt-1">Converted to {toAccount.currency} at the rate of the transaction date.</p>
          )}
          {isRefund &&
            (() => {
              const num = parseLocaleFloat(amount);
              if (!pickedRefund || isNaN(num) || num <= 0) return null;
              const { remaining, accountCurrency } = pickedRefund;
              if (num > remaining) {
                return (
                  <p className="text-xs text-muted mt-1">
                    Clears the {formatMoneyPrecise(remaining, accountCurrency)} left on that expense; the extra{" "}
                    {formatMoneyPrecise(num - remaining, accountCurrency)} counts as income.
                  </p>
                );
              }
              return (
                <p className="text-xs text-muted mt-1">
                  That expense will show as {formatMoneyPrecise(remaining - num, accountCurrency)} in reports from now on.
                </p>
              );
            })()}
        </div>
        <div>
          <label className="field-label">Date</label>
          {/* Capped at today, like every other date input in the app: the
              server refuses a future entry_date outright, so without this
              the picker happily offered dates it would then reject. */}
          <input
            type="date"
            className="input w-full"
            value={entryDate}
            onChange={(e) => setEntryDate(e.target.value)}
            max={todayISO()}
          />
        </div>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        {!isTransfer && !isRefund && (
          <div>
            <label className="field-label">Category (optional)</label>
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
        <div>
          <label className="field-label">Note (optional)</label>
          <input className="input w-full" value={note} onChange={(e) => setNote(e.target.value)} placeholder="e.g. Esselunga" />
        </div>
      </div>

      {kind === "INCOME" && (
        <div>
          <label className="field-label">Income type (optional)</label>
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

      {error && <p className="text-loss text-sm">{error}</p>}
      <button className="btn-primary" disabled={saving || !accountId}>
        {saving ? "Saving…" : isTransfer ? "⇄ Transfer" : isRefund ? "↩ Log refund" : kind === "EXPENSE" ? "+ Log expense" : "+ Log income"}
      </button>
    </form>
  );
}
