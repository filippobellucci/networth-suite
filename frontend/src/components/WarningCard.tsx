import type { ReactNode } from "react";

/**
 * The inline "something is degraded, here's what and what to do about it"
 * banner: a missing exchange rate, a price that wouldn't fetch, a failed
 * load -- one look, changed in one place.
 *
 * Purely presentational -- it decides nothing about when a warning shows.
 */
export default function WarningCard({ children }: { children: ReactNode }) {
  return (
    <div className="card p-4 border-loss/40 text-sm text-loss flex items-start gap-3">
      <span aria-hidden="true" className="grid place-items-center w-6 h-6 shrink-0 rounded-full bg-loss-soft font-bold text-xs">
        !
      </span>
      <div className="min-w-0 pt-0.5">{children}</div>
    </div>
  );
}
