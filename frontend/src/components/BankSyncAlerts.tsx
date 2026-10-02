import { useEffect, useState } from "react";
import { api } from "../api/client";
import { bankSyncAlerts, type BankSyncAlert } from "../lib/bankSyncAlerts";

/**
 * Bank sync problems worth acting on -- a consent about to run out, a link
 * that stopped syncing -- shown where the app is actually looked at. Renders
 * nothing when all is well, and nothing at all on an instance without bank
 * sync (the gateway answers 404 for a module it doesn't have).
 */
export default function BankSyncAlerts() {
  const [alerts, setAlerts] = useState<BankSyncAlert[]>([]);
  const [unreachable, setUnreachable] = useState(false);

  useEffect(() => {
    let cancelled = false;
    api
      .getBankSyncStatus()
      .then((s) => !cancelled && setAlerts(bankSyncAlerts(s)))
      .catch((e: { status?: number }) => {
        if (!cancelled && e?.status !== 404) setUnreachable(true);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (unreachable) {
    return (
      <div className="card p-4 border-loss/40 text-sm text-loss" role="alert">
        The bank sync service isn't reachable, so no new transactions are being captured. Check it in "Modules &amp;
        Status".
      </div>
    );
  }
  if (alerts.length === 0) return null;
  return (
    <div className="space-y-2" aria-label="Bank sync alerts">
      {alerts.map((a, i) => (
        <div
          key={`${a.label}-${i}`}
          role="alert"
          className={`card p-4 text-sm flex items-start justify-between gap-4 flex-wrap ${
            a.level === "error" ? "border-loss/40 text-loss" : "border-brass/40"
          }`}
        >
          <span>{a.message}</span>
          {a.actionUrl && (
            <a
              href={a.actionUrl}
              target="_blank"
              rel="noreferrer"
              className="text-brass text-xs font-medium whitespace-nowrap underline"
            >
              {a.actionLabel} ↗
            </a>
          )}
        </div>
      ))}
    </div>
  );
}
