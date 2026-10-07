import { useEffect, useState } from "react";
import { api } from "../api/client";
import type {
  Portfolio,
  CashAccount,
  ExpenseCategory,
  CashTransaction,
  InvestmentIncomeKind,
} from "../types";
import { formatMoneyPrecise, formatDate, todayISO, parseLocaleFloat } from "../lib/format";
import SegmentedControl from "./SegmentedControl";
import { errorText } from "../lib/errors";

type Kind = "INCOME" | "EXPENSE" | "TRANSFER" | "REFUND";

/**
 * Logs a new income, expense, transfer or refund against a cash account.
 * Owns every field of the entry form; tells the parent (via `onLogged`)
 * only once a transaction has actually been created, so it can refresh the
 * recent list and the refund candidates derived from it.
 */
export default function TransactionLogForm({
  portfolios,
  portfolioId,
  onPortfolioIdChange,
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
  portfolios: Portfolio[];
  portfolioId: string;
  onPortfolioIdChange: (id: string) => void;
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

  // A picked refund target belongs to the portfolio just left.
  useEffect(() => {
    setRefundOfId("");
  }, [portfolioId]);

  useEffect(() => {
    if (kind !== "TRANSFER") return;
    setToAccountId((current) => {
      if (current && current !== accountId && transferAccounts.some((a) => a.id === current)) return current;
      return transferAccounts.find((a) => a.id !== accountId)?.id ?? "";
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [kind, accountId, accounts]);

  // Expenses eligible to be refunded: real expenses only (no transfer legs,
  // and a refund itself can't be refunded), each annotated with how much of
  // it hasn't been refunded yet -- computed the same way the backend does
  // (sum every linked refund, floor at 0), just so the picker can show it.
  const refundCandidates = portfolioTransactions
    .filter((t) => t.direction === "EXPENSE" && !t.transfer_id && !t.refund_of_id)
    .map((expense) => {
      const alreadyRefunded = portfolioTransactions
        .filter((t) => t.refund_of_id === expense.id)
        .reduce((sum, t) => sum + t.amount, 0);
      const remaining = Math.max(0, expense.amount - alreadyRefunded);
      // allAccounts, not accounts: this expense may sit on an account that
      // has since been removed, which the active-only list cannot resolve.
      const account = allAccounts.find((a) => a.id === expense.account_id);
      // The backend nets a refund against its expense as raw numbers, with
      // no FX conversion (compute_refund_adjustments in core-networth) --
      // so `expense.amount`/`remaining` are always in the ORIGINAL
      // expense's own account currency, regardless of which account the
      // refund income is logged against. Carrying that currency along here
      // (instead of reusing whatever account happens to be selected at the
      // top of the form) is what the dropdown/hint below actually need.
      // Marked as removed so it's clear why this account isn't in the
      // picker at the top of the form, even though its expense is here.
      const accountName = account ? (account.archived_at ? `${account.name} (removed)` : account.name) : "";
      return { expense, remaining, accountName, accountCurrency: account?.currency ?? "EUR" };
    })
    .sort((a, b) => (b.remaining > 0 ? 1 : 0) - (a.remaining > 0 ? 1 : 0) || b.expense.entry_date.localeCompare(a.expense.entry_date));

  const toAccount = accounts.find((a) => a.id === toAccountId);
  // The expense currently picked in the refund dropdown -- looked up once
  // here rather than re-found inline everywhere the form describes it.
  const pickedRefund = refundCandidates.find((c) => c.expense.id === refundOfId);
  const refundCurrency = pickedRefund?.accountCurrency ?? selectedAccount?.currency;
  const isVoucher = kind !== "TRANSFER" && kind !== "REFUND" && selectedAccount?.kind === "VOUCHER";
  const isTransfer = kind === "TRANSFER";
  const isRefund = kind === "REFUND";

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
    <form onSubmit={handleSubmit} className="card p-6 space-y-4">
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <div>
          <label className="field-label">Portfolio</label>
          <select className="input w-full" value={portfolioId} onChange={(e) => onPortfolioIdChange(e.target.value)}>
            {portfolios.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className="field-label">
            {isTransfer ? "From account" : "Account"}
          </label>
          <select className="input w-full" value={accountId} onChange={(e) => onAccountIdChange(e.target.value)}>
            {accounts.length === 0 && <option value="">No eligible cash accounts in this portfolio</option>}
            {accounts.map((a) => (
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
          <select className="input w-full" value={refundOfId} onChange={(e) => setRefundOfId(e.target.value)}>
            <option value="">Select an expense…</option>
            {refundCandidates.map(({ expense, remaining, accountName, accountCurrency }) => (
              <option key={expense.id} value={expense.id}>
                {formatDate(expense.entry_date)} — {expense.note || "(no note)"} — {accountName} —{" "}
                {remaining > 0
                  ? `${formatMoneyPrecise(remaining, accountCurrency)} left of ${formatMoneyPrecise(expense.amount, accountCurrency)}`
                  : "fully refunded"}
              </option>
            ))}
          </select>
          {refundCandidates.length === 0 && (
            <p className="text-xs text-muted mt-1">No expenses logged in this portfolio yet.</p>
          )}
          {pickedRefund && selectedAccount && pickedRefund.accountCurrency !== selectedAccount.currency && (
            <p className="text-xs text-muted mt-1">
              This expense was in {pickedRefund.accountCurrency}; enter the amount in{" "}
              {pickedRefund.accountCurrency} below too (refunds aren't currency-converted, even when logged
              against a different-currency account).
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
                  // ORIGINAL expense's own amount with no FX conversion --
                  // so it must be entered in that expense's account
                  // currency, not whichever account is currently selected
                  // to receive the refund.
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
            <p className="text-xs text-muted mt-1">Converted to {toAccount.currency} at today's rate on arrival.</p>
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
