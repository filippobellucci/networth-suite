import { useEffect, useState, useCallback } from "react";
import { api } from "../api/client";
import type { NetWorthSnapshot } from "../types";
import { formatMoney, formatDate } from "../lib/format";
import NetWorthChart from "../components/NetWorthChart";
import InfoTooltip from "../components/InfoTooltip";

export default function HistoricalNetWorth() {
  const [snapshots, setSnapshots] = useState<NetWorthSnapshot[]>([]);
  const [loading, setLoading] = useState(true);
  const [taking, setTaking] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(() => {
    setLoading(true);
    api
      .listNetWorthSnapshots("EUR")
      .then(setSnapshots)
      .catch((e) => setError(String(e.message || e)))
      .finally(() => setLoading(false));
  }, []);

  useEffect(reload, [reload]);

  async function handleTakeSnapshot() {
    setTaking(true);
    setError(null);
    try {
      await api.takeNetWorthSnapshot("EUR");
      reload();
    } catch (e: any) {
      setError(String(e.message || e));
    } finally {
      setTaking(false);
    }
  }

  async function handleDelete(snap: NetWorthSnapshot) {
    if (!confirm(`Remove the snapshot from ${formatDate(snap.snapshot_date)}?`)) return;
    await api.deleteNetWorthSnapshot(snap.id);
    reload();
  }

  const chartPoints = [...snapshots]
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
            A frozen record of your combined net worth over time — unlike the live chart
            elsewhere, these numbers never change once taken. An end-of-month snapshot is taken
            automatically (backfilled with real historical prices if the machine was off that
            day), or press "Take snapshot" any time for an extra point.
          </p>
        </div>
        <button className="btn-primary text-sm shrink-0" onClick={handleTakeSnapshot} disabled={taking}>
          {taking ? "Taking snapshot…" : "+ Take snapshot"}
        </button>
      </div>

      {error && (
        <div className="card p-4 border-loss/40 text-sm text-loss">{error}</div>
      )}

      <div className="card p-8">
        <NetWorthChart points={chartPoints} currency="EUR" />
      </div>

      {loading ? (
        <div className="text-muted">Loading…</div>
      ) : snapshots.length === 0 ? (
        <div className="card p-6 text-muted text-sm">
          No snapshots yet. Press "Take snapshot" to record today's combined net worth as the
          first point in this history.
        </div>
      ) : (
        <div className="card overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs uppercase tracking-wide text-muted border-b ledger-rule">
                <th className="px-5 py-3 font-normal">Date</th>
                <th className="px-5 py-3 font-normal">Source</th>
                <th className="px-5 py-3 font-normal text-right">Net worth</th>
                <th className="px-5 py-3 font-normal text-right">Invested</th>
                <th className="px-5 py-3 font-normal text-right">Cash</th>
                <th className="px-5 py-3 font-normal"></th>
              </tr>
            </thead>
            <tbody className="font-mono">
              {snapshots.map((s) => (
                <tr key={s.id} className="border-b ledger-rule last:border-0">
                  <td className="px-5 py-3 font-sans">{formatDate(s.snapshot_date)}</td>
                  <td className="px-5 py-3 text-xs font-sans">
                    <span className="px-2 py-0.5 rounded-full border ledger-rule text-brass-dim">
                      {s.source === "auto" ? "Auto" : "Manual"}
                    </span>
                  </td>
                  <td className="px-5 py-3 text-right num">{formatMoney(s.net_worth, s.currency)}</td>
                  <td className="px-5 py-3 text-right num text-muted">{formatMoney(s.invested_total, s.currency)}</td>
                  <td className="px-5 py-3 text-right num text-muted">{formatMoney(s.cash_total, s.currency)}</td>
                  <td className="px-5 py-3 text-right font-sans">
                    <button className="text-muted hover:text-loss text-xs" onClick={() => handleDelete(s)}>
                      Remove
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
