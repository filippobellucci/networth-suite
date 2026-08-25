import { useEffect, useState, useCallback } from "react";
import { api } from "../api/client";
import type { Portfolio, CashAccount, ExpenseCategory, CashTransaction, TransactionDirection } from "../types";
import { formatMoneyPrecise, formatDate, todayISO } from "../lib/format";
import SegmentedControl from "../components/SegmentedControl";
import ResponsiveTable, { type ResponsiveColumn } from "../components/ResponsiveTable";

export default function Transactions() {
  const [portfolios, setPortfolios] = useState<Portfolio[]>([]);
  const [accounts, setAccounts] = useState<CashAccount[]>([]);
  const [categories, setCategories] = useState<ExpenseCategory[]>([]);
  const [recent, setRecent] = useState<CashTransaction[]>([]);

  const [portfolioId, setPortfolioId] = useState("");
  const [accountId, setAccountId] = useState("");
  const [direction, setDirection] = useState<TransactionDirection>("EXPENSE");
  const [amount, setAmount] = useState("");
  const [categoryId, setCategoryId] = useState("");
  const [entryDate, setEntryDate] = useState(todayISO());
  const [note, setNote] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.listPortfolios().then((list) => {
      setPortfolios(list);
      if (!portfolioId && list.length > 0) setPortfolioId(list[0].id);
    });
    api.listExpenseCategories().then(setCategories);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!portfolioId) return;
    api.listCashAccounts(portfolioId).then((list) => {
      // Pension Fund accounts stay hand-updated only (see PortfolioDetail) --
      // never offered here, so they can't accidentally end up managed by
      // both the manual "Update" flow and the transaction ledger at once.
      const eligible = list.filter((a) => a.category !== "PENSION_FUND");
      setAccounts(eligible);
      setAccountId((current) => (eligible.some((a) => a.id === current) ? current : eligible[0]?.id ?? ""));
    });
  }, [portfolioId]);

  const reloadRecent = useCallback(() => {
    if (!accountId) {
      setRecent([]);
      return;
    }
    api.listAccountTransactions(accountId).then((list) => setRecent(list.slice(0, 8)));
  }, [accountId]);

  useEffect(reloadRecent, [reloadRecent]);

  const selectedAccount = accounts.find((a) => a.id === accountId);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const num = parseFloat(amount);
    if (!accountId || isNaN(num) || num <= 0) {
      setError("Pick an account and enter a positive amount.");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await api.createCashTransaction(accountId, {
        entry_date: entryDate,
        direction,
        amount: num,
        category_id: categoryId || undefined,
        note: note.trim() || undefined,
      });
      // Keep portfolio/account/direction/date so a run of same-day entries
      // (e.g. logging today's receipts one by one) doesn't require
      // re-selecting them every time -- only amount/category/note reset.
      setAmount("");
      setCategoryId("");
      setNote("");
      reloadRecent();
    } catch (e: any) {
      setError(String(e.message || e));
    } finally {
      setSaving(false);
    }
  }

  async function handleDeleteRecent(t: CashTransaction) {
    if (!confirm("Remove this transaction?")) return;
    await api.deleteCashTransaction(t.id);
    reloadRecent();
  }

  return (
    <div className="space-y-8">
      <div>
        <h1 className="font-display text-2xl mb-1">Transactions</h1>
        <p className="text-muted text-sm">
          Log an income or expense against a cash account — its balance everywhere else in the app
          (Portfolio, Summary, Portfolio Allocation) updates automatically, and is no longer edited
          by hand.
        </p>
      </div>

      <form onSubmit={handleSubmit} className="card p-6 space-y-4">
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <div>
            <label className="text-xs uppercase tracking-wide text-muted block mb-1">Portfolio</label>
            <select className="input w-full" value={portfolioId} onChange={(e) => setPortfolioId(e.target.value)}>
              {portfolios.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="text-xs uppercase tracking-wide text-muted block mb-1">Account</label>
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
            ]}
            value={direction}
            onChange={setDirection}
          />
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <div>
            <label className="text-xs uppercase tracking-wide text-muted block mb-1">
              Amount {selectedAccount ? `(${selectedAccount.currency})` : ""}
            </label>
            <input
              className="input w-full"
              value={amount}
              onChange={(e) => setAmount(e.target.value)}
              placeholder="0.00"
              inputMode="decimal"
              autoFocus
            />
          </div>
          <div>
            <label className="text-xs uppercase tracking-wide text-muted block mb-1">Date</label>
            <input
              type="date"
              className="input w-full"
              value={entryDate}
              onChange={(e) => setEntryDate(e.target.value)}
            />
          </div>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
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
          <div>
            <label className="text-xs uppercase tracking-wide text-muted block mb-1">Note (optional)</label>
            <input className="input w-full" value={note} onChange={(e) => setNote(e.target.value)} placeholder="e.g. Esselunga" />
          </div>
        </div>

        {error && <p className="text-loss text-sm">{error}</p>}
        <button className="btn-primary" disabled={saving || !accountId}>
          {saving ? "Saving…" : direction === "EXPENSE" ? "+ Log expense" : "+ Log income"}
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
                      const cat = categories.find((c) => c.id === t.category_id);
                      return cat ? (
                        <span className="inline-flex items-center gap-1.5">
                          <span
                            className="inline-block w-2 h-2 rounded-full shrink-0"
                            style={{ backgroundColor: cat.color || "#75694C" }}
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
                      <span className={t.direction === "INCOME" ? "text-gain" : "text-loss"}>
                        {t.direction === "INCOME" ? "+" : "−"}
                        {formatMoneyPrecise(t.amount, selectedAccount.currency)}
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
        </div>
      )}
    </div>
  );
}
