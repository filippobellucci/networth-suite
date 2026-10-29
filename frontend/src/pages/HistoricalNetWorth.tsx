import { useEffect, useState, useCallback } from "react";
import { api } from "../api/client";
import type { NetWorthSnapshot } from "../types";
import { formatMoney, formatDate } from "../lib/format";
import NetWorthChart from "../components/NetWorthChart";
import InfoTooltip from "../components/InfoTooltip";
import WarningCard from "../components/WarningCard";
import ResponsiveTable, { type ResponsiveColumn } from "../components/ResponsiveTable";
import { errorText } from "../lib/errors";
import { useSelectedPortfolio } from "../context/PortfolioContext";

/** The selected portfolio's frozen snapshots, each in its base currency. */
export default function HistoricalNetWorth() {
  const portfolio = useSelectedPortfolio();
  const [snapshots, setSnapshots] = useState<NetWorthSnapshot[]>([]);
  const [loading, setLoading] = useState(true);
  const [taking, setTaking] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(() => {
    setLoading(true);
    api
      .listNetWorthSnapshots(portfolio.id)
      .then(setSnapshots)
      .catch((e) => setError(errorText(e)))
      .finally(() => setLoading(false));
  }, [portfolio.id]);

  useEffect(reload, [reload]);

  async function handleTakeSnapshot() {
    setTaking(true);
    setError(null);
    try {
      await api.takeNetWorthSnapshot(portfolio.id);
      reload();
    } catch (e) {
      setError(errorText(e));
    } finally {
      setTaking(false);
    }
  }

  async function handleDelete(snap: NetWorthSnapshot) {
    if (!confirm(`Remove the snapshot from ${formatDate(snap.snapshot_date)}?`)) return;
    setError(null);
    try {
      await api.deleteNetWorthSnapshot(snap.id);
    } catch (e) {
      setError(errorText(e));
      return;
    }
    reload();
  }

  // One line, one currency: a snapshot keeps the currency it was taken in,
  // so any taken before a change of base currency stays in the table only.
  const chartPoints = snapshots
    .filter((s) => s.currency === portfolio.base_currency)
    .sort((a, b) => a.snapshot_date.localeCompare(b.snapshot_date))
    .map((s) => ({ date: s.snapshot_date, net_worth_base_ccy: s.net_worth }));

  return (
    <div className="space-y-8">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="font-display text-2xl mb-1 flex items-center gap-2">
            Historical Net Worth
            <InfoTooltip>
              <p className="mb-2">
                These are <strong>frozen</strong> points in time — once a snapshot is taken, its
                value never changes, even if prices move afterwards.
              </p>
              <p>
                This is different from the live chart shown elsewhere in the app, which always
                re-values every holding at today's (or, for a past date, that date's real
                historical) price. Don't expect the two to always match exactly — that's by
                design, not a bug.
              </p>
            </InfoTooltip>
          </h1>
          <p className="text-muted text-sm">
            A frozen record of this portfolio's net worth over time, in {portfolio.base_currency} — unlike the live chart
            elsewhere, these numbers never change once taken. An end-of-month snapshot is taken
            automatically (backfilled with real historical prices if the machine was off that
            day), or press "Take snapshot" any time for an extra point.
          </p>
        </div>
        <button className="btn-primary text-sm shrink-0" onClick={handleTakeSnapshot} disabled={taking}>
          {taking ? "Taking snapshot…" : "+ Take snapshot"}
        </button>
      </div>

      {error && <WarningCard>{error}</WarningCard>}

      <div className="card p-8">
        <NetWorthChart points={chartPoints} currency={portfolio.base_currency} />
      </div>

      {loading ? (
        <div className="text-muted">Loading…</div>
      ) : snapshots.length === 0 ? (
        <div className="card p-6 text-muted text-sm">
          No snapshots yet. Press "Take snapshot" to record this portfolio's net worth today as
          the first point in this history.
        </div>
      ) : (
        <ResponsiveTable
          keyFor={(s) => s.id}
          rows={snapshots}
          columns={
            [
              { header: "Date", cell: (s) => formatDate(s.snapshot_date), className: "font-sans" },
              {
                header: "Source",
                className: "text-xs font-sans",
                cell: (s) => (
                  <span className="px-2 py-0.5 rounded-full border ledger-rule text-brass-dim">
                    {s.source === "auto" ? "Auto" : "Manual"}
                  </span>
                ),
              },
              {
                header: "Net worth",
                className: "text-right num",
                headClassName: "text-right",
                cell: (s) => formatMoney(s.net_worth, s.currency),
              },
              {
                header: "Invested",
                className: "text-right num text-muted",
                headClassName: "text-right",
                cell: (s) => formatMoney(s.invested_total, s.currency),
              },
              {
                header: "Cash",
                className: "text-right num text-muted",
                headClassName: "text-right",
                cell: (s) => formatMoney(s.cash_total, s.currency),
              },
              {
                header: "",
                noMobileLabel: true,
                className: "text-right font-sans",
                cell: (s) => (
                  <button className="text-muted hover:text-loss text-xs" onClick={() => handleDelete(s)}>
                    Remove
                  </button>
                ),
              },
            ] as ResponsiveColumn<NetWorthSnapshot>[]
          }
        />
      )}
    </div>
  );
}
