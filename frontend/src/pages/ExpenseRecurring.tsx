import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { ExpenseCategory, Portfolio, RecurringPayment, RecurringReport } from "../types";
import { formatDate, formatMoneyPrecise } from "../lib/format";
import ResponsiveTable, { type ResponsiveColumn } from "../components/ResponsiveTable";

const CADENCE_LABEL: Record<RecurringPayment["cadence"], string> = {
  WEEKLY: "Weekly",
  MONTHLY: "Monthly",
  QUARTERLY: "Quarterly",
  YEARLY: "Yearly",
};

/**
 * Subscriptions and other recurring payments, found automatically in the
 * last year or so of spending: same merchant, a steady rhythm, a steady
 * amount. Nothing to set up -- and a price that went up is pointed out.
 */
export default function ExpenseRecurring({
  portfolioId,
  onPortfolioIdChange,
}: {
  /** Shared with the other Expenses tabs; "" means every portfolio. */
  portfolioId: string;
  onPortfolioIdChange: (id: string) => void;
}) {
  const [report, setReport] = useState<RecurringReport | null>(null);
  const [categories, setCategories] = useState<ExpenseCategory[]>([]);
  const [portfolios, setPortfolios] = useState<Portfolio[]>([]);
  useEffect(() => {
    api.listPortfolios().then(setPortfolios).catch(() => {});
  }, []);
  const [showInactive, setShowInactive] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setError(null);
    Promise.all([api.getRecurring(portfolioId || undefined), api.listExpenseCategories()])
      .then(([r, c]) => {
        setReport(r);
        setCategories(c);
      })
      .catch((e) => setError(String(e.message || e)));
  }, [portfolioId]);

  if (error) return <p className="text-loss text-sm">{error}</p>;
  if (!report) return <div className="text-muted">Loading…</div>;

  const active = report.items.filter((i) => i.active);
  const inactive = report.items.filter((i) => !i.active);
  const rows = showInactive ? report.items : active;
  const raised = active.filter((i) => i.price_change && i.price_change.current > i.price_change.previous);
  const categoryName = (id?: string | null) => categories.find((c) => c.id === id)?.name ?? "—";

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <p className="text-muted text-sm max-w-2xl">
          Payments that repeat on a steady rhythm with a steady amount, found in the last year of spending — the
          merchant your bank reported, or the note on one you logged by hand.
        </p>
        <select
          className="input"
          value={portfolioId}
          onChange={(e) => onPortfolioIdChange(e.target.value)}
          aria-label="Portfolio"
        >
          <option value="">All portfolios</option>
          {portfolios.map((p) => (
            <option key={p.id} value={p.id}>
              {p.name}
            </option>
          ))}
        </select>
      </div>

      <div className="card p-6 flex items-baseline gap-6 flex-wrap">
        <div>
          <div className="text-xs uppercase tracking-wide text-muted">Active, per month</div>
          <div className="font-display text-3xl num" aria-label="Monthly total">
            {formatMoneyPrecise(report.monthly_total, report.currency)}
          </div>
        </div>
        <div className="text-sm text-muted">
          {active.length} active · about {formatMoneyPrecise(report.monthly_total * 12, report.currency)} a year
        </div>
      </div>

      {raised.length > 0 && (
        <div className="card p-4 text-sm border-loss/40" role="alert">
          {raised.map((i) => (
            <div key={i.key}>
              ▲ <span className="font-medium">{i.name}</span> went up from{" "}
              {formatMoneyPrecise(i.price_change!.previous, report.currency)} to{" "}
              {formatMoneyPrecise(i.price_change!.current, report.currency)} on {formatDate(i.price_change!.date)}.
            </div>
          ))}
        </div>
      )}

      {report.items.length === 0 ? (
        <div className="card p-6 text-muted text-sm">
          Nothing recurring found yet — it takes a few payments to the same merchant before a rhythm shows.
        </div>
      ) : (
        <>
          <ResponsiveTable
            keyFor={(i) => i.key}
            rows={rows}
            columns={
              [
                {
                  header: "Merchant",
                  cell: (i) => (
                    <span className={i.active ? "" : "text-muted"}>
                      {i.name}
                      {!i.active && <span className="text-xs ml-2">(stopped)</span>}
                    </span>
                  ),
                },
                { header: "Every", className: "text-xs", cell: (i) => CADENCE_LABEL[i.cadence] },
                {
                  header: "Amount",
                  className: "text-right num",
                  headClassName: "text-right",
                  cell: (i) => (
                    <span>
                      {formatMoneyPrecise(i.last_amount, report.currency)}
                      {i.price_change && (
                        <span className={`text-xs ml-1 ${i.price_change.current > i.price_change.previous ? "text-loss" : "text-gain"}`}>
                          {i.price_change.current > i.price_change.previous ? "▲" : "▼"}
                        </span>
                      )}
                    </span>
                  ),
                },
                {
                  header: "Per month",
                  className: "text-right num",
                  headClassName: "text-right",
                  cell: (i) => formatMoneyPrecise(i.monthly_cost, report.currency),
                },
                { header: "Category", className: "text-xs text-muted", cell: (i) => categoryName(i.category_id) },
                {
                  header: "Next",
                  className: "text-xs text-muted whitespace-nowrap",
                  cell: (i) => (i.active ? formatDate(i.next_expected) : `last ${formatDate(i.last_date)}`),
                },
              ] as ResponsiveColumn<RecurringPayment>[]
            }
          />
          {inactive.length > 0 && (
            <button className="text-muted text-xs hover:text-ink-text" onClick={() => setShowInactive((v) => !v)}>
              {showInactive ? "Hide" : "Show"} {inactive.length} that stopped
            </button>
          )}
        </>
      )}
    </div>
  );
}
