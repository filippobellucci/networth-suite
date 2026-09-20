import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import type { DashboardSummary, GrowthStats, XirrStats } from "../types";
import NetWorthChart from "../components/NetWorthChart";
import NetWorthStat from "../components/NetWorthStat";
import WarningCard from "../components/WarningCard";
import XirrLine from "../components/XirrLine";
import { formatMoney } from "../lib/format";

export default function Dashboard() {
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [growth, setGrowth] = useState<GrowthStats | null>(null);
  const [xirr, setXirr] = useState<XirrStats | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api
      .getDashboardSummary()
      .then(setSummary)
      .catch((e) => setError(String(e.message || e)))
      .finally(() => setLoading(false));
    api.getCombinedGrowth().then(setGrowth).catch(() => setGrowth(null));
    api.getCombinedXirr().then(setXirr).catch(() => setXirr(null));
  }, []);

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

  if (!summary) return null;

  // Converted by the backend (see DashboardSummary.totals). Summing the
  // per-portfolio snapshots here instead would add up figures expressed in
  // different currencies -- a dollar portfolio counted as euros -- and
  // disagree with the chart and the growth/XIRR figures right beside it.
  const currency = summary.base_currency ?? "EUR";
  const totals = summary.totals;
  const points = summary.combined_history?.points ?? [];
  // Two separate ways these figures can be off by a missing rate: a currency
  // inside one portfolio valued 1:1 (its snapshot says so), or a whole
  // portfolio converted 1:1 into the combined base currency (only `totals`
  // knows about that -- a dollar portfolio's own snapshot is perfectly fine).
  const fxUnavailable =
    summary.snapshots.some((s) => s.fx_unavailable) || Boolean(totals?.fx_unavailable);

  return (
    <div className="space-y-8">
      <div>
        <h1 className="font-display text-2xl mb-1">Summary</h1>
        <p className="text-muted text-sm">
          Combined net worth across all portfolios, converted to {currency}.
        </p>
      </div>

      {fxUnavailable && (
        <WarningCard>
          An exchange rate couldn't be fetched, so amounts in other currencies are counted here at
          1:1 — these totals are not converted correctly. Check the price-feed service in "Modules
          & Status".
        </WarningCard>
      )}

      <div className="card p-8">
        {/* null, not 0, when the totals didn't load: a missing figure must not
            be shown as a real zero net worth. */}
        <NetWorthStat label="Total net worth" value={totals?.net_worth ?? null} currency={currency} />

        <div className="grid grid-cols-2 gap-8 mt-6 pt-6 border-t ledger-rule">
          <NetWorthStat label="Invested" value={totals?.invested_total ?? null} currency={currency} size="md" />
          <NetWorthStat label="Other" value={totals?.cash_total ?? null} currency={currency} size="md" />
        </div>

        <XirrLine xirr={xirr} />

        <div className="mt-8">
          {/* Passed directly (not wrapped in a fresh arrow function) so its
              identity is stable across renders -- useIntradayData's effect
              is keyed on this function's identity, and a new one every
              render made it re-fetch and flash "Loading hourly prices…" on
              every unrelated re-render of this page while on "Day". */}
          <NetWorthChart points={points} growth={growth} fetchIntraday={api.getCombinedIntraday} />
        </div>
      </div>

      <div>
        <div className="flex items-center justify-between mb-3">
          <h2 className="font-display text-lg">Portfolios</h2>
          <Link to="/portfolios" className="text-brass text-sm hover:underline">
            Manage portfolios →
          </Link>
        </div>

        {/* Keyed on `portfolios`, not `snapshots`: the gateway drops any
            snapshot whose request failed, so valuing them going wrong left a
            user with portfolios staring at "No portfolios yet" -- an invitation
            to create duplicates of the ones they already have. */}
        {summary.portfolios.length === 0 ? (
          <div className="card p-6 text-muted text-sm">
            No portfolios yet.{" "}
            <Link to="/portfolios" className="text-brass hover:underline">
              Create one
            </Link>{" "}
            to start tracking your net worth.
          </div>
        ) : summary.snapshots.length === 0 ? (
          <div className="card p-6 text-muted text-sm">
            Your portfolios couldn't be valued right now. Check the core service in "Modules &
            Status".
          </div>
        ) : (
          <div className="grid grid-cols-2 gap-4">
            {summary.snapshots.map((snap) => (
              <Link
                key={snap.portfolio_id}
                to={`/portfolios/${snap.portfolio_id}`}
                className="card p-5 hover:border-brass-dim transition-colors"
              >
                <p className="text-sm text-muted mb-1">{snap.portfolio_name}</p>
                <p className="font-display text-2xl num">
                  {formatMoney(snap.net_worth_base_ccy, snap.base_currency)}
                </p>
                <div className="flex gap-4 mt-3 text-xs text-muted">
                  <span>Invested {formatMoney(snap.invested_total_base_ccy, snap.base_currency)}</span>
                  <span>Cash {formatMoney(snap.cash_total_base_ccy, snap.base_currency)}</span>
                </div>
              </Link>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
