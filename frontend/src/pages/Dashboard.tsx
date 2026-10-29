import { useCallback, useEffect, useId, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import type { BudgetProgress, GrowthPeriod, GrowthStats, NetWorthHistory, NetWorthPoint, PortfolioSnapshot, XirrPeriod, XirrStats } from "../types";
import NetWorthChart from "../components/NetWorthChart";
import NetWorthStat from "../components/NetWorthStat";
import WarningCard from "../components/WarningCard";
import BankSyncAlerts from "../components/BankSyncAlerts";
import ResponsiveTable, { type ResponsiveColumn } from "../components/ResponsiveTable";
import { XirrInfo } from "../components/XirrLine";
import { GROWTH_KEYS, GrowthBadge, pointsInRange, type RangeKey } from "../components/chartHelpers";
import { formatDate, formatMoney, formatPct } from "../lib/format";
import { errorText } from "../lib/errors";
import { useSelectedPortfolio } from "../context/PortfolioContext";

const PERIODS: { range: RangeKey; label: string }[] = [
  { range: "W", label: "Past week" },
  { range: "M", label: "Past month" },
  { range: "Y", label: "Past year" },
];

function signedMoney(value: number, currency: string) {
  return `${value >= 0 ? "+" : "−"}${formatMoney(Math.abs(value), currency)}`;
}

/**
 * A minimal line of the net worth over a period, with the period's starting
 * value as a dashed reference line. Decorative: the figures beside it carry
 * the information.
 */
function Sparkline({ values, baseline }: { values: number[]; baseline: number | null }) {
  const gradientId = useId();
  if (values.length < 2) {
    return <div className="h-16 grid place-items-center text-xs text-muted">Not enough history yet</div>;
  }
  const W = 200;
  const H = 64;
  const PAD = 6;
  const all = baseline === null ? values : [...values, baseline];
  const min = Math.min(...all);
  const span = Math.max(...all) - min || 1;
  const x = (i: number) => (i / (values.length - 1)) * W;
  const y = (v: number) => PAD + (1 - (v - min) / span) * (H - 2 * PAD);
  const line = values.map((v, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" ");
  const last = values[values.length - 1];
  return (
    <div className="relative h-16" aria-hidden="true">
      <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" className="w-full h-full overflow-visible">
        <defs>
          <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="var(--color-brass)" stopOpacity={0.28} />
            <stop offset="100%" stopColor="var(--color-brass)" stopOpacity={0} />
          </linearGradient>
        </defs>
        {baseline !== null && (
          <line x1={0} x2={W} y1={y(baseline)} y2={y(baseline)} stroke="var(--color-muted)" strokeDasharray="3 4" strokeWidth={1} vectorEffect="non-scaling-stroke" opacity={0.6} />
        )}
        <path d={`${line} L${W},${H} L0,${H} Z`} fill={`url(#${gradientId})`} />
        <path d={line} fill="none" stroke="var(--color-brass)" strokeWidth={1.8} strokeLinejoin="round" vectorEffect="non-scaling-stroke" />
      </svg>
      <span
        className="absolute w-2.5 h-2.5 -translate-x-1/2 -translate-y-1/2 rounded-full bg-ink border-2 border-brass"
        style={{ left: "100%", top: `${(y(last) / H) * 100}%` }}
      />
    </div>
  );
}

/** One "label ····· value" line under a figure. */
function LeaderRow({ label, value, className = "" }: { label: string; value: string; className?: string }) {
  return (
    <div className="flex items-baseline gap-2">
      <dt className="text-muted">{label}</dt>
      <span className="flex-1 border-b border-dotted ledger-rule" />
      <dd className={`num ${className}`}>{value}</dd>
    </div>
  );
}

function PeriodTile({ label, growth, points, range, currency }: {
  label: string;
  growth: GrowthPeriod | null;
  points: NetWorthPoint[];
  range: RangeKey;
  currency: string;
}) {
  const values = pointsInRange(points, range).map((p) => p.net_worth_base_ccy);
  const positive = (growth?.change ?? 0) >= 0;
  return (
    <div className="rounded-2xl bg-ink-raised border ledger-rule p-4 flex flex-col min-w-0">
      <p className="text-sm font-medium">{label}</p>
      <div className="mt-3">
        <Sparkline values={values} baseline={growth?.start_value ?? null} />
      </div>
      {growth ? (
        <>
          <p className={`mt-4 font-display text-3xl font-light num ${positive ? "text-gain" : "text-loss"}`}>
            {growth.change_pct !== null
              ? `${positive ? "+" : "−"}${Math.abs(growth.change_pct).toFixed(1)}%`
              : signedMoney(growth.change, currency)}
          </p>
          <dl className="mt-3 space-y-1.5 text-xs">
            <LeaderRow label="Change" value={signedMoney(growth.change, currency)} />
            <LeaderRow label="Since" value={formatDate(growth.start_date)} />
          </dl>
        </>
      ) : (
        <p className="mt-4 font-display text-3xl font-light text-muted">—</p>
      )}
    </div>
  );
}

function XirrItem({ label, period, info }: { label: string; period: XirrPeriod | null; info?: boolean }) {
  return (
    <div className="flex items-center gap-3 flex-1 min-w-0 px-2">
      <span className="grid place-items-center w-10 h-10 shrink-0 rounded-xl bg-ink-raised border ledger-rule text-brass" aria-hidden="true">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
          <path d="M3 17l6-6 4 4 8-8" />
          <path d="M15 7h6v6" />
        </svg>
      </span>
      <div className="min-w-0">
        <p className="text-xs text-muted flex items-center gap-1.5">
          {label}
          {info && <XirrInfo />}
        </p>
        {period ? (
          <p className={`text-sm font-semibold num ${period.rate_pct >= 0 ? "text-gain" : "text-loss"}`}>
            {period.rate_pct >= 0 ? "+" : ""}
            {period.rate_pct.toFixed(1)}% <span className="text-muted font-normal">a year</span>
          </p>
        ) : (
          <p className="text-sm text-muted">Not enough history yet</p>
        )}
      </div>
    </div>
  );
}

/** A 270° ring; `value` is a percentage, null draws the empty track. */
function Gauge({ value }: { value: number | null }) {
  const r = 52;
  const circumference = 2 * Math.PI * r;
  const arc = circumference * 0.75;
  const filled = value === null ? 0 : (Math.min(Math.max(value, 0), 100) / 100) * arc;
  return (
    <div className="relative w-36 h-36 shrink-0">
      <svg viewBox="0 0 120 120" className="w-full h-full rotate-[135deg]" aria-hidden="true">
        <circle cx="60" cy="60" r={r} fill="none" stroke="var(--color-ink-raised)" strokeWidth="9" strokeLinecap="round" strokeDasharray={`${arc} ${circumference}`} />
        {filled > 0 && (
          <circle cx="60" cy="60" r={r} fill="none" stroke="var(--color-brass)" strokeWidth="9" strokeLinecap="round" strokeDasharray={`${filled} ${circumference}`} className="drop-shadow-[0_0_8px_var(--color-brass)]" />
        )}
      </svg>
      <span className="absolute inset-0 grid place-items-center font-display text-3xl font-light num">
        {value === null ? "—" : `${Math.round(value)}%`}
      </span>
    </div>
  );
}

function BudgetsCard({ progress, error }: { progress: BudgetProgress | null; error: string | null }) {
  const items = progress ? [...progress.items].sort((a, b) => b.percent - a.percent).slice(0, 4) : [];
  return (
    <section className="card p-6">
      <div className="flex items-center justify-between gap-3 mb-5">
        <h2 className="font-display text-lg">Budgets this month</h2>
        {progress && <span className="text-sm text-muted num">{progress.elapsed_pct}% of the month gone</span>}
      </div>
      {error ? (
        <p className="text-loss text-sm">Budgets couldn't be loaded: {error}</p>
      ) : !progress ? (
        <p className="text-muted text-sm">Loading…</p>
      ) : items.length === 0 ? (
        <p className="text-muted text-sm">
          No budgets set yet.{" "}
          <Link to="/expenses" className="text-brass hover:underline">
            Add one under Expenses → Budgets
          </Link>
          .
        </p>
      ) : (
        <div className="space-y-4">
          {items.map((item) => (
            <div key={item.budget_id}>
              <div className="flex items-baseline justify-between gap-3 text-sm mb-2">
                <span className="truncate">{item.category_name}</span>
                <span className="num text-xs">
                  {formatMoney(item.spent, item.currency)} <span className="text-muted">of {formatMoney(item.budget, item.currency)}</span>
                </span>
              </div>
              <div className="meter" role="meter" aria-valuemin={0} aria-valuemax={item.budget} aria-valuenow={item.spent} aria-label={`${item.category_name}: ${item.percent}% of the budget used`}>
                <span
                  style={{
                    width: `${Math.min(item.percent, 100)}%`,
                    background: item.status === "OVER" ? "var(--color-loss)" : item.status === "NEAR" ? "#D97706" : undefined,
                  }}
                />
              </div>
            </div>
          ))}
        </div>
      )}
      <Link to="/expenses" className="mt-5 inline-block text-brass text-sm hover:underline">
        All budgets →
      </Link>
    </section>
  );
}

/** One line of the holdings card: a position or a cash-like balance, valued in the base currency. */
interface HoldingRow {
  key: string;
  name: string;
  kind: string;
  value: number;
}

function largestHoldings(snapshot: PortfolioSnapshot, count: number): HoldingRow[] {
  // An unpriced position has no value to rank by; the warning above the cards names it.
  const rows: HoldingRow[] = [
    ...snapshot.positions.flatMap((p) =>
      p.value_base_ccy == null
        ? []
        : [{ key: `a-${p.asset_id}`, name: p.asset_name, kind: p.ticker ?? "Position", value: p.value_base_ccy }]
    ),
    ...snapshot.cash_positions.map((c) => ({
      key: `c-${c.account_id}`,
      name: c.account_name,
      kind: c.currency,
      value: c.value_base_ccy,
    })),
  ];
  return rows.sort((a, b) => b.value - a.value).slice(0, count);
}

/** The selected portfolio at a glance: its total, performance, history, holdings and budgets. */
export default function Dashboard() {
  const portfolio = useSelectedPortfolio();
  const [snapshot, setSnapshot] = useState<PortfolioSnapshot | null>(null);
  const [history, setHistory] = useState<NetWorthHistory | null>(null);
  const [growth, setGrowth] = useState<GrowthStats | null>(null);
  const [xirr, setXirr] = useState<XirrStats | null>(null);
  const [budgets, setBudgets] = useState<BudgetProgress | null>(null);
  const [budgetsError, setBudgetsError] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api
      .getSnapshot(portfolio.id)
      .then(setSnapshot)
      .catch((e) => setError(errorText(e)))
      .finally(() => setLoading(false));
    api.getHistory(portfolio.id).then(setHistory).catch(() => setHistory(null));
    api.getPortfolioGrowth(portfolio.id).then(setGrowth).catch(() => setGrowth(null));
    api.getPortfolioXirr(portfolio.id).then(setXirr).catch(() => setXirr(null));
    api.getBudgetProgress(portfolio.id).then(setBudgets).catch((e) => setBudgetsError(errorText(e)));
  }, [portfolio.id]);

  // Stable identity: useIntradayData's effect is keyed on it.
  const fetchIntraday = useCallback(() => api.getPortfolioIntraday(portfolio.id), [portfolio.id]);

  if (loading) return <div className="text-muted">Loading summary…</div>;

  if (error) {
    return (
      <div className="card p-6 border-loss/40">
        <p className="text-loss font-medium mb-1">Could not reach the gateway</p>
        <p className="text-muted text-sm">{error}</p>
        <p className="text-muted text-sm mt-2">
          Check that all backend services are running (see the "Modules & Status" tab).
        </p>
      </div>
    );
  }

  if (!snapshot) return null;

  const currency = snapshot.base_currency;
  const points = history?.points ?? [];
  // A holding whose price couldn't be fetched contributes nothing to the
  // total, so the headline figure is simply too low with no sign of it.
  const unpricedHoldings = snapshot.positions.filter((p) => p.price_source === "unavailable").map((p) => p.asset_name);
  // A share only means something when both parts are non-negative: a
  // negative balance would push the other part past 100%.
  const invested = snapshot.invested_total_base_ccy;
  const other = snapshot.cash_total_base_ccy;
  const investedShare =
    invested >= 0 && other >= 0 && invested + other > 0 ? (invested / (invested + other)) * 100 : null;
  const holdings = largestHoldings(snapshot, 6);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="font-display text-3xl font-semibold mb-1">Summary</h1>
        <p className="text-muted text-sm">
          {portfolio.name}, in {currency}.
        </p>
      </div>

      <BankSyncAlerts />

      {snapshot.fx_unavailable && (
        <WarningCard>
          An exchange rate couldn't be fetched, so amounts in other currencies are counted here at
          1:1 — these totals are not converted correctly. Check the price-feed service in "Modules
          & Status".
        </WarningCard>
      )}

      {unpricedHoldings.length > 0 && (
        <WarningCard>
          No price could be fetched for {unpricedHoldings.join(", ")} — {unpricedHoldings.length === 1
            ? "that holding is"
            : "those holdings are"}{" "}
          missing from the totals below, so your real net worth is higher than what's shown. Check
          the ticker on the portfolio page, and the price-feed service in "Modules & Status".
        </WarningCard>
      )}

      <div className="grid gap-5 lg:grid-cols-12">
        <section className="card overflow-hidden p-7 lg:col-span-5 lg:row-span-2 flex flex-col items-center text-center">
          <div aria-hidden="true" className="absolute inset-x-0 bottom-0 h-3/4 bg-gradient-to-t from-brass/30 via-brass/5 to-transparent pointer-events-none" />
          <div className="orb mt-1" aria-hidden="true">
            <span />
            <span />
          </div>
          <div className="relative mt-6 w-full">
            <NetWorthStat label="Total net worth" value={snapshot.net_worth_base_ccy} currency={currency} />
            <div className="mt-3 flex justify-center">
              <GrowthBadge growth={growth?.day} currency={currency} formatMoney={formatMoney} />
            </div>
            <div className="grid grid-cols-2 gap-4 mt-6 pt-5 border-t ledger-rule">
              <NetWorthStat label="Invested" value={invested} currency={currency} size="md" />
              <NetWorthStat label="Other" value={other} currency={currency} size="md" />
            </div>
            <div className="mt-7 flex justify-center gap-3 flex-wrap">
              <Link to="/expenses" className="btn-primary text-sm">
                Log a transaction <span aria-hidden="true">›</span>
              </Link>
              <Link to={`/portfolios/${portfolio.id}`} className="btn-ghost text-sm">
                Open portfolio
              </Link>
            </div>
          </div>
        </section>

        <section className="card p-5 lg:col-span-7 flex flex-col">
          <div className="flex items-center justify-between gap-3 mb-4">
            <h2 className="font-display text-lg">Performance</h2>
            <span className="text-xs text-muted px-3 py-1.5 rounded-full bg-ink-raised border ledger-rule">{currency}</span>
          </div>
          <div className="grid gap-3 sm:grid-cols-3 flex-1">
            {PERIODS.map((p) => (
              <PeriodTile
                key={p.range}
                label={p.label}
                range={p.range}
                growth={growth ? growth[GROWTH_KEYS[p.range]] : null}
                points={points}
                currency={currency}
              />
            ))}
          </div>
        </section>

        <section className="card p-4 lg:col-span-7 flex flex-col sm:flex-row gap-4 sm:gap-0 sm:divide-x divide-panel-hairline">
          <XirrItem label="Annualized return · 1Y" period={xirr?.year ?? null} info />
          <XirrItem label="Annualized return · all time" period={xirr?.max ?? null} />
        </section>

        <section className="card p-6 lg:col-span-12">
          <h2 className="font-display text-lg mb-4">Net worth over time</h2>
          <NetWorthChart points={points} currency={currency} growth={growth} fetchIntraday={fetchIntraday} height={300} />
        </section>

        <section className="lg:col-span-7 space-y-3">
          <div className="flex items-center justify-between px-1">
            <h2 className="font-display text-lg">Largest holdings</h2>
            <Link to={`/portfolios/${portfolio.id}`} className="text-brass text-sm hover:underline">
              All positions →
            </Link>
          </div>
          {holdings.length === 0 ? (
            <div className="card p-6 text-muted text-sm">
              Nothing in this portfolio yet.{" "}
              <Link to={`/portfolios/${portfolio.id}`} className="text-brass hover:underline">
                Add a position or a balance
              </Link>
              .
            </div>
          ) : (
            <ResponsiveTable
              keyFor={(h) => h.key}
              rows={holdings}
              columns={
                [
                  { header: "Holding", cell: (h) => <span className="font-medium">{h.name}</span> },
                  { header: "", className: "text-xs text-muted", cell: (h) => h.kind },
                  {
                    header: "Value",
                    className: "text-right num",
                    headClassName: "text-right",
                    cell: (h) => formatMoney(h.value, currency),
                  },
                ] as ResponsiveColumn<HoldingRow>[]
              }
            />
          )}
        </section>

        <div className="lg:col-span-5 flex flex-col gap-5">
          <section className="card p-6 flex items-center gap-5">
            <div className="flex-1 min-w-0">
              <h2 className="font-display text-lg">Invested share</h2>
              <p className="text-muted text-sm mt-1">How much of your net worth is invested; the rest is cash and other balances.</p>
              {investedShare !== null && (
                <p className="text-sm mt-4">
                  <span className="text-muted">Other: </span>
                  <span className="num font-medium">{formatPct(100 - investedShare)}</span>
                </p>
              )}
            </div>
            <Gauge value={investedShare} />
          </section>
          <BudgetsCard progress={budgets} error={budgetsError} />
        </div>
      </div>
    </div>
  );
}
