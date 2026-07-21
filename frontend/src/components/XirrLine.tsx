import type { XirrStats } from "../types";
import InfoTooltip from "./InfoTooltip";

export default function XirrLine({ xirr }: { xirr: XirrStats | null }) {
  if (!xirr || (!xirr.year && !xirr.max)) return null;

  return (
    <div className="flex items-center gap-5 mt-6 pt-6 border-t ledger-rule text-sm">
      <span className="flex items-center gap-1.5 text-xs uppercase tracking-wide text-muted">
        Annualized return (XIRR)
        <InfoTooltip>
          <p className="mb-2">
            This is your <strong>money-weighted annual return</strong> — how fast your own
            invested money is actually growing, separate from how much of it you've added or
            withdrawn.
          </p>
          <p className="mb-2">
            A plain "value today vs. value before" comparison can't tell apart real growth from
            money you simply added. XIRR fixes that by looking at every deposit or withdrawal on
            its actual date, then solving for the constant annual rate that would explain the
            change in value.
          </p>
          <p className="mb-2">
            <strong>1Y</strong> uses only the last year of activity; <strong>All-time</strong>{" "}
            uses everything since your first tracked entry. If both show the same number, it
            usually means you have less than a year of history so far — they'll diverge naturally
            once more time has passed.
          </p>
          <p className="mb-2">
            Note: with only a few days or weeks of real history, this rate gets annualized from a
            very short period, which can produce very large-looking numbers even from a small
            actual gain — this settles down as more history builds up.
          </p>
          <p>
            One known simplification: for cash accounts, a balance increase is always treated as
            a deposit, even if part of it was interest earned rather than money added.
          </p>
        </InfoTooltip>
      </span>
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
