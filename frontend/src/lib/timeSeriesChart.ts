import type { GrowthStats } from "../types";

/**
 * Shared range/formatting logic for the D/W/M/Y/Max area-chart pattern used
 * by both NetWorthChart and AssetPriceChart. Previously duplicated almost
 * verbatim in both files; extracted here so there's one place to change.
 * The actual chart rendering lives in components/TimeSeriesChart.tsx.
 */

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
