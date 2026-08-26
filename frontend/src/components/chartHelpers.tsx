import { useEffect, useState } from "react";
import { formatDate } from "../lib/format";
import type { GrowthStats } from "../types";

export type RangeKey = "D" | "W" | "M" | "Y" | "MAX";
export type DisplayMode = "absolute" | "percentage";

export const RANGE_LABELS: Record<RangeKey, string> = { D: "Day", W: "Week", M: "Month", Y: "Year", MAX: "Max" };
export const GROWTH_KEYS: Record<RangeKey, keyof Omit<GrowthStats, "current">> = {
  D: "day",
  W: "week",
  M: "month",
  Y: "year",
  MAX: "max",
};

export function cutoffFor(range: RangeKey): Date | null {
  if (range === "MAX") return null;
  const d = new Date();
  if (range === "D") d.setDate(d.getDate() - 1);
  if (range === "W") d.setDate(d.getDate() - 7);
  if (range === "M") d.setMonth(d.getMonth() - 1);
  if (range === "Y") d.setFullYear(d.getFullYear() - 1);
  return d;
}

export function formatHour(iso: string): string {
  return new Date(iso).toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit" });
}

export function formatPctTick(v: number): string {
  return `${v >= 0 ? "+" : ""}${v.toFixed(1)}%`;
}

/** Converts a series of {..., value} points into percentage-change-from-first-point form. */
export function toPercentage<T extends { value: number }>(rows: T[]): T[] {
  if (rows.length === 0) return rows;
  const base = rows[0].value;
  if (!base) return rows.map((r) => ({ ...r, value: 0 }));
  return rows.map((r) => ({ ...r, value: ((r.value - base) / base) * 100 }));
}

/**
 * Shared by NetWorthChart and AssetPriceChart: fetches hourly points only
 * when "Day" is selected and an intraday fetcher was provided, resetting to
 * null the rest of the time. Generic over the point type since the two
 * callers use different shapes (IntradayPoint vs AssetIntradayPoint).
 */
export function useIntradayData<T>(range: RangeKey, fetchIntraday?: () => Promise<T[]>) {
  const [intraday, setIntraday] = useState<T[] | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (range !== "D" || !fetchIntraday) {
      setIntraday(null);
      return;
    }
    let cancelled = false;
    setLoading(true);
    fetchIntraday()
      .then((pts) => {
        if (!cancelled) setIntraday(pts);
      })
      .catch(() => {
        if (!cancelled) setIntraday([]);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [range, fetchIntraday]);

  return { intraday, loading };
}

type GrowthPoint = GrowthStats[keyof Omit<GrowthStats, "current">];

/**
 * The "+€X (+Y%) since <date>" badge shown next to a chart's range control.
 * Takes the money formatter as a prop since NetWorthChart uses formatMoney
 * and AssetPriceChart uses formatMoneyPrecise -- a real, deliberate
 * difference (net worth rounds to whole units, a single asset's price
 * needs decimals), not something to collapse into one choice.
 */
export function GrowthBadge({
  growth,
  currency,
  formatMoney,
}: {
  growth: GrowthPoint | null | undefined;
  currency: string;
  formatMoney: (value: number, currency: string) => string;
}) {
  if (!growth) return <div />;
  return (
    <div className="text-sm">
      <span className={growth.change >= 0 ? "text-gain" : "text-loss"}>
        {growth.change >= 0 ? "+" : ""}
        {formatMoney(growth.change, currency)}
        {growth.change_pct !== null && (
          <> ({growth.change >= 0 ? "+" : ""}{growth.change_pct.toFixed(1)}%)</>
        )}
      </span>
      <span className="text-muted ml-1.5">since {formatDate(growth.start_date)}</span>
    </div>
  );
}
