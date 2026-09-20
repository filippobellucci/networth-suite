import type { ReactNode } from "react";

/**
 * The inline "something is degraded, here's what and what to do about it"
 * banner: a missing exchange rate, a price that wouldn't fetch, a failed
 * load. Four pages had the same class string written out by hand, so the
 * warnings had already started drifting apart visually; this keeps them
 * one look, changed in one place.
 *
 * Purely presentational -- it decides nothing about when a warning shows.
 */
export default function WarningCard({ children }: { children: ReactNode }) {
  return <div className="card p-4 border-loss/40 text-sm text-loss">{children}</div>;
}
