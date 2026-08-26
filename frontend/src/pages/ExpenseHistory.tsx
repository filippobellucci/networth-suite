import { useEffect, useState, useCallback } from "react";
import { PieChart, Pie, Cell, Tooltip, ResponsiveContainer } from "recharts";
import { api } from "../api/client";
import type { Portfolio, CashAccount, ExpenseCategory, CashTransaction, ExpenseSummary } from "../types";
import { formatMoney, formatMoneyPrecise, formatDate, formatPct, todayISO } from "../lib/format";
import { useTheme } from "../context/ThemeContext";
import { usePalette } from "../context/PaletteContext";
import { getChartTheme } from "../lib/chartTheme";
import NetWorthStat from "../components/NetWorthStat";
import SegmentedControl from "../components/SegmentedControl";
import ResponsiveTable, { type ResponsiveColumn } from "../components/ResponsiveTable";

type QuickRange = "month" | "year" | "all" | "custom";

function firstOfMonth(): string {
  const d = new Date();
  return new Date(d.getFullYear(), d.getMonth(), 1).toISOString().slice(0, 10);
}
function firstOfYear(): string {
  return new Date(new Date().getFullYear(), 0, 1).toISOString().slice(0, 10);
}

export default function ExpenseHistory() {
  const { theme } = useTheme();
  const { palette } = usePalette();
  const chart = getChartTheme(theme === "dark", palette);

  const [portfolios, setPortfolios] = useState<Portfolio[]>([]);
  const [accountsByPortfolio, setAccountsByPortfolio] = useState<Record<string, CashAccount[]>>({});
  const [categories, setCategories] = useState<ExpenseCategory[]>([]);

  const [portfolioId, setPortfolioId] = useState<string>("");
  const [quickRange, setQuickRange] = useState<QuickRange>("month");
  const [fromDate, setFromDate] = useState(firstOfMonth());
  const [toDate, setToDate] = useState(todayISO());

  const [summary, setSummary] = useState<ExpenseSummary | null>(null);
  const [transactions, setTransactions] = useState<CashTransaction[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.listPortfolios().then(setPortfolios);
    api.listExpenseCategories().then(setCategories);
  }, []);

  // Account names/currencies are needed to label rows in the movements
  // table below -- fetched for every portfolio (or just the selected one)
  // since there's no single "all accounts" endpoint.
  useEffect(() => {
    const targets = portfolioId ? portfolios.filter((p) => p.id === portfolioId) : portfolios;
    if (targets.length === 0) return;
    Promise.all(targets.map((p) => api.listCashAccounts(p.id).then((accts) => [p.id, accts] as const))).then(
      (pairs) => setAccountsByPortfolio(Object.fromEntries(pairs))
    );
  }, [portfolioId, portfolios]);

  function applyQuickRange(r: QuickRange) {
    setQuickRange(r);
    if (r === "month") {
      setFromDate(firstOfMonth());
      setToDate(todayISO());
    } else if (r === "year") {
      setFromDate(firstOfYear());
      setToDate(todayISO());
    } else if (r === "all") {
      setFromDate("2000-01-01");
      setToDate(todayISO());
    }
    // "custom" leaves the current from/to as-is -- the date inputs below take over.
  }

  const reload = useCallback(() => {
    setLoading(true);
    setError(null);
    Promise.all([
      api.getExpensesSummary({ from_date: fromDate, to_date: toDate, portfolio_id: portfolioId || undefined }),
      api.listTransactions({
        portfolio_id: portfolioId || undefined,
        from_date: fromDate,
        to_date: toDate,
      }),
    ])
      .then(([summ, txns]) => {
        setSummary(summ);
        setTransactions(txns);
      })
      .catch((e) => setError(String(e.message || e)))
      .finally(() => setLoading(false));
  }, [portfolioId, fromDate, toDate]);

  useEffect(reload, [reload]);

  async function handleDelete(t: CashTransaction) {
    if (!confirm("Remove this transaction?")) return;
    await api.deleteCashTransaction(t.id);
    reload();
  }

  const allAccounts = Object.values(accountsByPortfolio).flat();
  const accountFor = (id: string) => allAccounts.find((a) => a.id === id);
  const categoryFor = (id: string | null | undefined) => categories.find((c) => c.id === id);

  return (
    <div className="space-y-8">
      <div className="card p-6 flex items-center justify-between flex-wrap gap-3">
        <SegmentedControl
          options={[
            { value: "month", label: "This month" },
            { value: "year", label: "This year" },
            { value: "all", label: "All time" },
            { value: "custom", label: "Custom" },
          ]}
          value={quickRange}
          onChange={applyQuickRange}
        />
        <div className="flex items-center gap-3 flex-wrap">
          {quickRange === "custom" && (
            <>
              <input type="date" className="input" value={fromDate} onChange={(e) => setFromDate(e.target.value)} />
              <span className="text-muted text-sm">to</span>
              <input type="date" className="input" value={toDate} onChange={(e) => setToDate(e.target.value)} />
            </>
          )}
          <select className="input" value={portfolioId} onChange={(e) => setPortfolioId(e.target.value)}>
            <option value="">All portfolios</option>
            {portfolios.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
        </div>
      </div>

      {error && <p className="text-loss text-sm">{error}</p>}

      {loading ? (
        <p className="text-muted text-sm">Loading…</p>
      ) : (
        summary && (
          <div className="card p-6">
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-6 mb-6">
              <NetWorthStat label="Income" value={summary.total_income} currency={summary.currency} size="md" />
              <NetWorthStat label="Expense" value={summary.total_expense} currency={summary.currency} size="md" />
              <NetWorthStat label="Net" value={summary.net} currency={summary.currency} size="md" />
            </div>

            {summary.by_category.length === 0 ? (
              <p className="text-muted text-sm">No expenses in this period yet.</p>
            ) : (
              <div className="flex flex-col md:flex-row items-center gap-6 pt-4 border-t ledger-rule">
                <ResponsiveContainer width="100%" height={280} className="md:max-w-sm">
                  <PieChart>
                    <Pie
                      data={summary.by_category}
                      dataKey="total"
                      nameKey="category_name"
                      innerRadius={60}
                      outerRadius={120}
                      paddingAngle={1}
                      stroke={chart.panelBg}
                      strokeWidth={2}
                    >
                      {summary.by_category.map((s, i) => (
                        <Cell
                          key={s.category_id ?? "uncategorized"}
                          fill={categoryFor(s.category_id ?? undefined)?.color || chart.categorical[i % chart.categorical.length]}
                        />
                      ))}
                    </Pie>
                    <Tooltip
                      contentStyle={{ background: chart.panelBg, border: `1px solid ${chart.grid}`, borderRadius: 6, fontSize: 12 }}
                      formatter={(v: any, _name: any, item: any) => [
                        formatMoney(Number(v), summary.currency),
                        item?.payload?.category_name,
                      ]}
                    />
                  </PieChart>
                </ResponsiveContainer>

                <div className="flex-1 w-full">
                  <ResponsiveTable
                    keyFor={(s) => s.category_id ?? "uncategorized"}
                    rows={summary.by_category}
                    columns={
                      [
                        {
                          header: "Category",
                          cell: (s) => {
                            const i = summary.by_category.indexOf(s);
                            const color = categoryFor(s.category_id ?? undefined)?.color || chart.categorical[i % chart.categorical.length];
                            return (
                              <>
                                <span
                                  className="inline-block w-2.5 h-2.5 rounded-full mr-2 align-middle"
                                  style={{ backgroundColor: color }}
                                />
                                {s.category_name}
                              </>
                            );
                          },
                        },
                        {
                          header: "Total",
                          className: "text-right font-mono num",
                          headClassName: "text-right",
                          cell: (s) => formatMoney(s.total, summary.currency),
                        },
                        {
                          header: "Share",
                          className: "text-right font-mono num text-muted",
                          headClassName: "text-right",
                          cell: (s) => formatPct(summary.total_expense ? (s.total / summary.total_expense) * 100 : 0),
                        },
                      ] as ResponsiveColumn<(typeof summary.by_category)[number]>[]
                    }
                  />
                </div>
              </div>
            )}
          </div>
        )
      )}

      <div>
        <h2 className="font-display text-lg mb-3">Movements</h2>
        {!loading && transactions.length === 0 ? (
          <div className="card p-6 text-muted text-sm">No transactions in this period.</div>
        ) : (
          <ResponsiveTable
            keyFor={(t) => t.id}
            rows={transactions}
            columns={
              [
                { header: "Date", cell: (t) => formatDate(t.entry_date), className: "font-sans" },
                {
                  header: "Account",
                  className: "font-sans text-xs text-muted",
                  cell: (t) => accountFor(t.account_id)?.name ?? "—",
                },
                {
                  header: "Category",
                  className: "text-xs font-sans",
                  cell: (t) => {
                    const cat = categoryFor(t.category_id);
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
                  cell: (t) => {
                    const acc = accountFor(t.account_id);
                    return (
                      <span className={t.direction === "INCOME" ? "text-gain" : "text-loss"}>
                        {t.direction === "INCOME" ? "+" : "−"}
                        {formatMoneyPrecise(t.amount, acc?.currency ?? "EUR")}
                        {t.quantity != null && <span className="text-muted text-xs ml-1">({t.quantity}×)</span>}
                      </span>
                    );
                  },
                },
                {
                  header: "",
                  noMobileLabel: true,
                  className: "text-right font-sans",
                  cell: (t) => (
                    <button className="text-muted hover:text-loss text-xs" onClick={() => handleDelete(t)}>
                      Remove
                    </button>
                  ),
                },
              ] as ResponsiveColumn<CashTransaction>[]
            }
          />
        )}
      </div>
    </div>
  );
}
