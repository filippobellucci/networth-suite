import type { XirrStats } from "../types";

export default function XirrLine({ xirr }: { xirr: XirrStats | null }) {
  if (!xirr || (!xirr.year && !xirr.max)) return null;

  return (
    <div className="flex items-center gap-5 mt-6 pt-6 border-t ledger-rule text-sm">
      <span className="text-xs uppercase tracking-wide text-muted">Annualized return (XIRR)</span>
      {xirr.year && (
        <span>
          <span className="text-muted">1Y </span>
          <span className={xirr.year.rate_pct >= 0 ? "text-gain" : "text-loss"}>
            {xirr.year.rate_pct >= 0 ? "+" : ""}
            {xirr.year.rate_pct.toFixed(1)}%
          </span>
        </span>
      )}
      {xirr.max && (
        <span>
          <span className="text-muted">All-time </span>
          <span className={xirr.max.rate_pct >= 0 ? "text-gain" : "text-loss"}>
            {xirr.max.rate_pct >= 0 ? "+" : ""}
            {xirr.max.rate_pct.toFixed(1)}%
          </span>
        </span>
      )}
    </div>
  );
}
