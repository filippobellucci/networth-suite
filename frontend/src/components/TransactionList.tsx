import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../api/client";
import type { CashAccount, ExpenseCategory, CashTransaction, TransactionDirection, TransactionFilters } from "../types";
import { formatMoneyPrecise, formatDate, parseLocaleFloat } from "../lib/format";
import SegmentedControl from "./SegmentedControl";
import ResponsiveTable, { type ResponsiveColumn } from "./ResponsiveTable";
import { ConvertToTransferForm, EditTransactionForm } from "./TransactionEditors";
import { errorText } from "../lib/errors";
import { INVESTMENT_INCOME_LABELS } from "../lib/investmentIncome";

const RECENT_PAGE_SIZE = 8;

// A transfer leg is never categorized, and a refund is never given one
// either (it's netted against its expense instead).
const categorizable = (t: CashTransaction) => !t.transfer_id && !t.refund_of_id;

/**
 * The recent transactions on `selectedAccount`: search/filter, bulk
 * categorize, inline edit/convert-to-transfer, CSV export, pagination. Owns
 * its own list and filter state; only tells the parent (via
 * `onTransactionsChanged`) when a write here should also refresh the
 * portfolio-wide list the refund picker in the log form is computed from.
 */
export default function TransactionList({
  selectedAccount,
  categories,
  transferAccounts,
  accountId,
  reloadKey,
  onTransactionsChanged,
}: {
  selectedAccount: CashAccount;
  categories: ExpenseCategory[];
  /** Accounts a transfer leg may use -- vouchers don't support transfers. */
  transferAccounts: CashAccount[];
  accountId: string;
  /** Bumped by the parent whenever the log form creates a transaction, to refetch this list. */
  reloadKey: number;
  onTransactionsChanged: () => void;
}) {
  const [recent, setRecent] = useState<CashTransaction[]>([]);
  const [recentHasMore, setRecentHasMore] = useState(false);
  const [loadingMoreRecent, setLoadingMoreRecent] = useState(false);

  // The list under the form: "Uncategorized" narrows it to what's still
  // waiting for a category (what bank sync captures without one).
  const [onlyUncategorized, setOnlyUncategorized] = useState(false);
  const [editing, setEditing] = useState<CashTransaction | null>(null);
  const [converting, setConverting] = useState<CashTransaction | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [bulkCategoryId, setBulkCategoryId] = useState("");
  const [bulkSaving, setBulkSaving] = useState(false);
  const [listError, setListError] = useState<string | null>(null);
  const [listNotice, setListNotice] = useState<string | null>(null);

  // Search and filters for the list. The text is applied a moment after
  // typing stops, not on every keystroke.
  const [showFilters, setShowFilters] = useState(false);
  const [searchText, setSearchText] = useState("");
  const [search, setSearch] = useState("");
  const [filterCategory, setFilterCategory] = useState("");
  const [filterDirection, setFilterDirection] = useState<"" | TransactionDirection>("");
  const [filterFrom, setFilterFrom] = useState("");
  const [filterTo, setFilterTo] = useState("");
  const [filterMin, setFilterMin] = useState("");
  const [filterMax, setFilterMax] = useState("");
  useEffect(() => {
    const t = setTimeout(() => setSearch(searchText.trim()), 300);
    return () => clearTimeout(t);
  }, [searchText]);
  const filters: TransactionFilters = useMemo(() => {
    const amount = (raw: string) => (raw.trim() ? parseLocaleFloat(raw) : undefined);
    return {
      q: search || undefined,
      category_id: filterCategory || undefined,
      direction: filterDirection || undefined,
      from_date: filterFrom || undefined,
      to_date: filterTo || undefined,
      min_amount: amount(filterMin),
      max_amount: amount(filterMax),
    };
  }, [search, filterCategory, filterDirection, filterFrom, filterTo, filterMin, filterMax]);
  const activeFilterCount = Object.values(filters).filter((v) => v !== undefined && !(typeof v === "number" && isNaN(v))).length;
  function clearFilters() {
    setSearchText("");
    setSearch("");
    setFilterCategory("");
    setFilterDirection("");
    setFilterFrom("");
    setFilterTo("");
    setFilterMin("");
    setFilterMax("");
  }
  const [exporting, setExporting] = useState(false);
  async function exportCsv() {
    setExporting(true);
    setListError(null);
    try {
      await api.downloadTransactionsCsv({ account_id: accountId, filters });
    } catch (e) {
      setListError(errorText(e));
    } finally {
      setExporting(false);
    }
  }

  const reloadRecent = useCallback(() => {
    // Whatever was being edited or picked belongs to the list being replaced.
    setEditing(null);
    setConverting(null);
    setSelected(new Set());
    if (!accountId) {
      setRecent([]);
      setRecentHasMore(false);
      return;
    }
    api
      .listAccountTransactions(accountId, {
        limit: RECENT_PAGE_SIZE,
        offset: 0,
        uncategorized: onlyUncategorized,
        filters,
      })
      .then((list) => {
        setRecent(list);
        setRecentHasMore(list.length === RECENT_PAGE_SIZE);
      })
      .catch((e) => setListError(errorText(e)));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [accountId, onlyUncategorized, filters, reloadKey]);

  useEffect(reloadRecent, [reloadRecent]);

  function loadMoreRecent() {
    if (!accountId) return;
    setLoadingMoreRecent(true);
    api
      .listAccountTransactions(accountId, {
        limit: RECENT_PAGE_SIZE,
        offset: recent.length,
        uncategorized: onlyUncategorized,
        filters,
      })
      .then((more) => {
        setRecent((prev) => [...prev, ...more]);
        setRecentHasMore(more.length === RECENT_PAGE_SIZE);
      })
      .finally(() => setLoadingMoreRecent(false));
  }

  /** After an edit, a conversion or a bulk change: the list, and the
   * portfolio-wide list the refund picker is computed from. */
  function afterListChange(notice: string | null = null) {
    reloadRecent();
    setListNotice(notice);
    setListError(null);
    onTransactionsChanged();
  }

  function toggleSelected(id: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  async function applyBulkCategory() {
    if (selected.size === 0) return;
    setBulkSaving(true);
    setListError(null);
    try {
      const res = await api.bulkCategorize([...selected], bulkCategoryId || null);
      const name = categories.find((c) => c.id === bulkCategoryId)?.name;
      afterListChange(
        `${res.updated} transaction${res.updated === 1 ? "" : "s"} ${name ? `moved to ${name}` : "left without a category"}.`
      );
      setBulkCategoryId("");
    } catch (e) {
      setListError(errorText(e));
    } finally {
      setBulkSaving(false);
    }
  }

  async function handleDeleteRecent(t: CashTransaction) {
    if (!confirm("Remove this transaction?")) return;
    try {
      await api.deleteCashTransaction(t.id);
    } catch (e) {
      setListError(errorText(e));
      return;
    }
    reloadRecent();
    // Also refreshed here: the refund picker's "how much is left on this
    // expense" figures are derived from this list.
    onTransactionsChanged();
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <h2 className="font-display text-lg">Recent on {selectedAccount.name}</h2>
        <SegmentedControl
          options={[
            { value: "all", label: "All" },
            { value: "uncategorized", label: "Uncategorized" },
          ]}
          value={onlyUncategorized ? "uncategorized" : "all"}
          onChange={(v) => {
            setListNotice(null);
            setOnlyUncategorized(v === "uncategorized");
          }}
        />
      </div>

      <div className="flex items-center gap-3 flex-wrap">
        <input
          className="input flex-1 min-w-[12rem]"
          type="search"
          value={searchText}
          onChange={(e) => setSearchText(e.target.value)}
          placeholder="Search note or merchant…"
          aria-label="Search transactions"
        />
        <button className="btn-ghost text-sm" onClick={() => setShowFilters((v) => !v)} aria-expanded={showFilters}>
          Filters{activeFilterCount > 0 ? ` (${activeFilterCount})` : ""}
        </button>
        {activeFilterCount > 0 && (
          <button className="text-muted text-xs hover:text-ink-text" onClick={clearFilters}>
            Clear
          </button>
        )}
        <button className="btn-ghost text-sm" onClick={exportCsv} disabled={exporting}>
          {exporting ? "Exporting…" : "Export CSV"}
        </button>
      </div>
      {showFilters && (
        <div className="card p-4 grid grid-cols-2 sm:grid-cols-3 gap-3" aria-label="Transaction filters">
          <div>
            <label className="field-label">Type</label>
            <select
              className="input w-full"
              value={filterDirection}
              onChange={(e) => setFilterDirection(e.target.value as "" | TransactionDirection)}
            >
              <option value="">Any</option>
              <option value="EXPENSE">Expenses</option>
              <option value="INCOME">Income</option>
            </select>
          </div>
          <div>
            <label className="field-label">Category</label>
            <select className="input w-full" value={filterCategory} onChange={(e) => setFilterCategory(e.target.value)}>
              <option value="">Any</option>
              {categories.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="field-label">From</label>
            <input type="date" className="input w-full" value={filterFrom} onChange={(e) => setFilterFrom(e.target.value)} />
          </div>
          <div>
            <label className="field-label">To</label>
            <input type="date" className="input w-full" value={filterTo} onChange={(e) => setFilterTo(e.target.value)} />
          </div>
          <div>
            <label className="field-label">Min amount</label>
            <input
              className="input w-full"
              inputMode="decimal"
              value={filterMin}
              onChange={(e) => setFilterMin(e.target.value)}
            />
          </div>
          <div>
            <label className="field-label">Max amount</label>
            <input
              className="input w-full"
              inputMode="decimal"
              value={filterMax}
              onChange={(e) => setFilterMax(e.target.value)}
            />
          </div>
        </div>
      )}

      {listNotice && <p className="text-gain text-sm">{listNotice}</p>}
      {listError && <p className="text-loss text-sm">{listError}</p>}

      {editing && (
        <EditTransactionForm
          key={editing.id}
          txn={editing}
          account={selectedAccount}
          categories={categories}
          onDone={() => afterListChange("Saved.")}
          onCancel={() => setEditing(null)}
        />
      )}
      {converting && (
        <ConvertToTransferForm
          key={converting.id}
          txn={converting}
          account={selectedAccount}
          candidates={transferAccounts.filter((a) => a.id !== selectedAccount.id)}
          onDone={() => afterListChange("Now a transfer — it no longer counts as income or spending.")}
          onCancel={() => setConverting(null)}
        />
      )}

      {selected.size > 0 && (
        <div className="card p-3 flex items-center gap-3 flex-wrap" aria-label="Bulk categorize">
          <span className="text-sm">{selected.size} selected</span>
          <select
            className="input text-sm"
            value={bulkCategoryId}
            onChange={(e) => setBulkCategoryId(e.target.value)}
            aria-label="Category for the selected transactions"
          >
            <option value="">No category</option>
            {categories.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </select>
          <button className="btn-primary text-sm" onClick={applyBulkCategory} disabled={bulkSaving}>
            {bulkSaving ? "Saving…" : "Apply to selected"}
          </button>
          <button className="btn-ghost text-sm" onClick={() => setSelected(new Set())}>
            Clear selection
          </button>
        </div>
      )}

      {recent.length === 0 ? (
        <div className="card p-6 text-muted text-sm">
          {activeFilterCount > 0
            ? "Nothing matches these filters."
            : onlyUncategorized
              ? "Nothing left to categorize on this account."
              : "No transactions on this account yet."}
        </div>
      ) : (
        <ResponsiveTable
          keyFor={(t) => t.id}
          rows={recent}
          columns={
            [
              {
                header: "",
                noMobileLabel: true,
                className: "w-8",
                cell: (t) =>
                  categorizable(t) ? (
                    <input
                      type="checkbox"
                      aria-label="Select for bulk categorize"
                      checked={selected.has(t.id)}
                      onChange={() => toggleSelected(t.id)}
                    />
                  ) : null,
              },
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
                  if (t.investment_income_kind) {
                    return <span className="text-gain">◆ {INVESTMENT_INCOME_LABELS[t.investment_income_kind]}</span>;
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
              {
                header: "Note",
                className: "text-muted text-xs font-sans",
                cell: (t) => (
                  <>
                    {t.note || "—"}
                    {/* Shown only when it adds something: Revolut's note usually *is* the merchant name. */}
                    {t.counterparty && t.counterparty.toLowerCase() !== (t.note ?? "").toLowerCase() && (
                      <span className="block text-[11px]">{t.counterparty}</span>
                    )}
                  </>
                ),
              },
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
                  <span className="inline-flex gap-3 justify-end">
                    {!t.transfer_id && (
                      <button
                        className="text-brass text-xs"
                        onClick={() => {
                          setConverting(null);
                          setEditing(t);
                        }}
                      >
                        Edit
                      </button>
                    )}
                    {categorizable(t) && selectedAccount.kind !== "VOUCHER" && (
                      <button
                        className="text-muted hover:text-ink-text text-xs"
                        title="This was money moved between your own accounts"
                        onClick={() => {
                          setEditing(null);
                          setConverting(t);
                        }}
                      >
                        ⇄ Transfer
                      </button>
                    )}
                    <button className="text-muted hover:text-loss text-xs" onClick={() => handleDeleteRecent(t)}>
                      Remove
                    </button>
                  </span>
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
  );
}
