import { useEffect, useState, useCallback } from "react";
import { api } from "../api/client";
import type { Portfolio, CashAccount, ExpenseCategory, CashTransaction, TransactionDirection } from "../types";
import { formatMoneyPrecise, formatDate, todayISO, parseLocaleFloat } from "../lib/format";
import SegmentedControl from "../components/SegmentedControl";
import ResponsiveTable, { type ResponsiveColumn } from "../components/ResponsiveTable";

type Kind = TransactionDirection | "TRANSFER" | "REFUND";

interface TransactionsProps {
  /** Lifted up to Expenses.tsx so the selected portfolio is shared across
   * the Log/Categories/History tabs instead of resetting when switching
   * tabs. */
  portfolioId: string;
  onPortfolioIdChange: (id: string) => void;
}

export default function Transactions({ portfolioId, onPortfolioIdChange }: TransactionsProps) {
  const [portfolios, setPortfolios] = useState<Portfolio[]>([]);
  const [accounts, setAccounts] = useState<CashAccount[]>([]);
  /** Same portfolio, archived ones included — used only to label existing
   * rows (see the refund picker), never to offer somewhere to log to. */
  const [allAccounts, setAllAccounts] = useState<CashAccount[]>([]);
  const [categories, setCategories] = useState<ExpenseCategory[]>([]);
  const [recent, setRecent] = useState<CashTransaction[]>([]);
  const [recentHasMore, setRecentHasMore] = useState(false);
  const [loadingMoreRecent, setLoadingMoreRecent] = useState(false);
  const RECENT_PAGE_SIZE = 8;

  const [accountId, setAccountId] = useState("");
  const [toAccountId, setToAccountId] = useState("");
  const [refundOfId, setRefundOfId] = useState("");
  const [portfolioTransactions, setPortfolioTransactions] = useState<CashTransaction[]>([]);
  const [kind, setKind] = useState<Kind>("EXPENSE");
  const [amount, setAmount] = useState("");
  const [categoryId, setCategoryId] = useState("");
  const [entryDate, setEntryDate] = useState(todayISO());
  const [note, setNote] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.listPortfolios().then((list) => {
      setPortfolios(list);
      if (!portfolioId && list.length > 0) onPortfolioIdChange(list[0].id);
    });
    api.listExpenseCategories().then(setCategories);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!portfolioId) return;
    // Two lists on purpose. The pickers below must only ever offer accounts
    // you can still log against, but the refund picker DESCRIBES expenses
    // that already exist -- and an expense on a since-removed account is
    // still refundable (the backend only requires the refund to land in the
    // same portfolio and the same currency). Resolved against the active
    // list alone, such an expense showed a blank account name and defaulted
    // to EUR, so the dropdown told you to enter euros for what the server
    // then rejected as "this expense is in USD".
    api.listCashAccounts(portfolioId, true).then(setAllAccounts).catch(() => setAllAccounts([]));
    api.listCashAccounts(portfolioId).then((list) => {
      // Pension Fund accounts stay hand-updated only (see PortfolioDetail) --
      // never offered here, so they can't accidentally end up managed by
      // both the manual "Update" flow and the transaction ledger at once.
      const eligible = list.filter((a) => a.category !== "PENSION_FUND");
      setAccounts(eligible);
      setAccountId((current) => (eligible.some((a) => a.id === current) ? current : eligible[0]?.id ?? ""));
    });
    api.listTransactions({ portfolio_id: portfolioId }).then(setPortfolioTransactions);
    // A picked refund target belongs to the portfolio just left -- unlike
    // accountId/toAccountId above, this had no reset, so switching
    // portfolios mid-pick left a stale id queued to submit even though the
    // dropdown itself (driven by the new portfolio's refundCandidates) no
    // longer shows anything selected.
    setRefundOfId("");
  }, [portfolioId]);

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

  // Transfers don't support voucher accounts (see the backend's /transfers
  // rejection) -- a separate, narrower list for the "From"/"To" pickers.
  const transferAccounts = accounts.filter((a) => a.kind !== "VOUCHER");

  useEffect(() => {
    if (kind !== "TRANSFER") return;
    setToAccountId((current) => {
      if (current && current !== accountId && transferAccounts.some((a) => a.id === current)) return current;
      return transferAccounts.find((a) => a.id !== accountId)?.id ?? "";
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [kind, accountId, accounts]);

  const reloadRecent = useCallback(() => {
    if (!accountId) {
      setRecent([]);
      setRecentHasMore(false);
      return;
    }
    api.listAccountTransactions(accountId, { limit: RECENT_PAGE_SIZE, offset: 0 }).then((list) => {
      setRecent(list);
      setRecentHasMore(list.length === RECENT_PAGE_SIZE);
    });
  }, [accountId]);

  useEffect(reloadRecent, [reloadRecent]);

  function loadMoreRecent() {
    if (!accountId) return;
    setLoadingMoreRecent(true);
    api
      .listAccountTransactions(accountId, { limit: RECENT_PAGE_SIZE, offset: recent.length })
      .then((more) => {
        setRecent((prev) => [...prev, ...more]);
        setRecentHasMore(more.length === RECENT_PAGE_SIZE);
      })
      .finally(() => setLoadingMoreRecent(false));
  }

  const selectedAccount = accounts.find((a) => a.id === accountId);
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
      reloadRecent();
      api.listTransactions({ portfolio_id: portfolioId }).then(setPortfolioTransactions);
    } catch (e: any) {
      setError(String(e.message || e));
    } finally {
      setSaving(false);
    }
  }

  async function handleDeleteRecent(t: CashTransaction) {
    if (!confirm("Remove this transaction?")) return;
    try {
      await api.deleteCashTransaction(t.id);
    } catch (e: any) {
      setError(String(e.message || e));
      return;
    }
    reloadRecent();
    // Also refreshed here: the refund picker's "how much is left on this
    // expense" figures are derived from this list, so deleting an expense
    // (or one of its refunds) left the dropdown offering amounts computed
    // from a transaction that no longer exists until the page was reloaded.
    api.listTransactions({ portfolio_id: portfolioId }).then(setPortfolioTransactions).catch(() => {});
  }

  return (
    <div className="space-y-8">
      <form onSubmit={handleSubmit} className="card p-6 space-y-4">
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <div>
            <label className="text-xs uppercase tracking-wide text-muted block mb-1">Portfolio</label>
            <select className="input w-full" value={portfolioId} onChange={(e) => onPortfolioIdChange(e.target.value)}>
              {portfolios.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="text-xs uppercase tracking-wide text-muted block mb-1">
              {isTransfer ? "From account" : "Account"}
            </label>
            <select className="input w-full" value={accountId} onChange={(e) => setAccountId(e.target.value)}>
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
            <label className="text-xs uppercase tracking-wide text-muted block mb-1">To account</label>
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
            <label className="text-xs uppercase tracking-wide text-muted block mb-1">Expense being refunded</label>
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
            <label className="text-xs uppercase tracking-wide text-muted block mb-1">
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
            <label className="text-xs uppercase tracking-wide text-muted block mb-1">Date</label>
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
              <label className="text-xs uppercase tracking-wide text-muted block mb-1">Category (optional)</label>
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
            <label className="text-xs uppercase tracking-wide text-muted block mb-1">Note (optional)</label>
            <input className="input w-full" value={note} onChange={(e) => setNote(e.target.value)} placeholder="e.g. Esselunga" />
          </div>
        </div>

        {error && <p className="text-loss text-sm">{error}</p>}
        <button className="btn-primary" disabled={saving || !accountId}>
          {saving ? "Saving…" : isTransfer ? "⇄ Transfer" : isRefund ? "↩ Log refund" : kind === "EXPENSE" ? "+ Log expense" : "+ Log income"}
        </button>
      </form>

      {selectedAccount && (
        <div>
          <h2 className="font-display text-lg mb-3">Recent on {selectedAccount.name}</h2>
          {recent.length === 0 ? (
            <div className="card p-6 text-muted text-sm">No transactions on this account yet.</div>
          ) : (
            <ResponsiveTable
              keyFor={(t) => t.id}
              rows={recent}
              columns={
                [
                  { header: "Date", cell: (t) => formatDate(t.entry_date), className: "font-sans" },
                  {
                    header: "Category",
                    className: "text-xs font-sans",
                    cell: (t) => {
                      if (t.transfer_id) {
                        return <span className="text-muted">⇄ Transfer</span>;
                      }
                      if (t.refund_of_id) {
                        return <span className="text-gain">↩ Refund</span>;
                      }
                      const cat = categories.find((c) => c.id === t.category_id);
                      return cat ? (
                        <span className="inline-flex items-center gap-1.5">
                          <span
                            className="inline-block w-2 h-2 rounded-full shrink-0"
                            style={{ backgroundColor: cat.color || "#9CA3AF" }}
                          />
                          {cat.name}
                        </span>
                      ) : (
                        <span className="text-muted">—</span>
                      );
                    },
                  },
                  { header: "Note", className: "text-muted text-xs font-sans", cell: (t) => t.note || "—" },
                  {
                    header: "Amount",
                    className: "text-right num",
                    headClassName: "text-right",
                    cell: (t) => (
                      <span className={t.transfer_id ? "text-ink-text" : t.direction === "INCOME" ? "text-gain" : "text-loss"}>
                        {t.transfer_id ? (t.direction === "INCOME" ? "⇄ +" : "⇄ −") : t.direction === "INCOME" ? "+" : "−"}
                        {formatMoneyPrecise(t.amount, selectedAccount.currency)}
                        {t.quantity != null && <span className="text-muted text-xs ml-1">({t.quantity}×)</span>}
                      </span>
                    ),
                  },
                  {
                    header: "",
                    noMobileLabel: true,
                    className: "text-right font-sans",
                    cell: (t) => (
                      <button className="text-muted hover:text-loss text-xs" onClick={() => handleDeleteRecent(t)}>
                        Remove
                      </button>
                    ),
                  },
                ] as ResponsiveColumn<CashTransaction>[]
              }
            />
          )}
          {recentHasMore && (
            <div className="flex justify-center mt-4">
              <button className="btn-ghost text-sm" onClick={loadMoreRecent} disabled={loadingMoreRecent}>
                {loadingMoreRecent ? "Loading…" : "Load more"}
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
