import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import type { DashboardSummary, GrowthStats } from "../types";
import NetWorthChart from "../components/NetWorthChart";
import NetWorthStat from "../components/NetWorthStat";
import { formatMoney } from "../lib/format";

export default function Dashboard() {
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [growth, setGrowth] = useState<GrowthStats | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api
      .getDashboardSummary()
      .then(setSummary)
      .catch((e) => setError(String(e.message || e)))
      .finally(() => setLoading(false));
    api.getCombinedGrowth().then(setGrowth).catch(() => setGrowth(null));
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

  const totalNetWorth = summary.snapshots.reduce((sum, s) => sum + s.net_worth_base_ccy, 0);
  const totalInvested = summary.snapshots.reduce((sum, s) => sum + s.invested_total_base_ccy, 0);
  const totalCash = summary.snapshots.reduce((sum, s) => sum + s.cash_total_base_ccy, 0);
  const points = summary.combined_history?.points ?? [];

  return (
    <div className="space-y-8">
      <div>
        <h1 className="font-display text-2xl mb-1">Summary</h1>
        <p className="text-muted text-sm">
          Combined net worth across all portfolios, converted to EUR.
        </p>
      </div>

      <div className="card p-8">
        <NetWorthStat label="Total net worth" value={totalNetWorth} />

        <div className="grid grid-cols-2 gap-8 mt-6 pt-6 border-t ledger-rule">
          <NetWorthStat label="Invested" value={totalInvested} size="md" />
          <NetWorthStat label="Cash" value={totalCash} size="md" />
        </div>

        <div className="mt-8">
          <NetWorthChart points={points} growth={growth} fetchIntraday={() => api.getCombinedIntraday()} />
        </div>
      </div>

      <div>
        <div className="flex items-center justify-between mb-3">
          <h2 className="font-display text-lg">Portfolios</h2>
          <Link to="/portfolios" className="text-brass text-sm hover:underline">
            Manage portfolios →
          </Link>
        </div>

        {summary.snapshots.length === 0 ? (
          <div className="card p-6 text-muted text-sm">
            No portfolios yet.{" "}
            <Link to="/portfolios" className="text-brass hover:underline">
              Create one
            </Link>{" "}
            to start tracking your net worth.
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
