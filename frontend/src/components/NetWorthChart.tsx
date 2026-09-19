import { useMemo } from "react";
import type { NetWorthPoint, GrowthStats, IntradayPoint } from "../types";
import { formatMoney } from "../lib/format";
import RangeAreaChart from "./RangeAreaChart";
import type { RangeKey } from "./chartHelpers";

const RANGES: RangeKey[] = ["D", "W", "M", "Y", "MAX"];

export default function NetWorthChart({
  points,
  currency = "EUR",
  height = 260,
  growth,
  fetchIntraday,
}: {
  points: NetWorthPoint[];
  currency?: string;
  height?: number;
  /** Optional day/week/month/year/max growth stats, shown next to the range buttons. */
  growth?: GrowthStats | null;
  /**
   * If provided, selecting "Day" fetches real hourly prices via this instead
   * of just showing the (at most daily-granularity) points already loaded.
   */
  fetchIntraday?: () => Promise<IntradayPoint[]>;
}) {
  const rows = useMemo(
    () => points.map((p) => ({ date: p.date, value: p.net_worth_base_ccy })),
    [points]
  );

  // Memoized on the incoming fetcher's identity: useIntradayData's effect is
  // keyed on the function it receives, so a new wrapper on every render would
  // re-fetch and flash "Loading hourly prices…" on every unrelated re-render
  // of the page while on "Day".
  const fetchHourly = useMemo(
    () =>
      fetchIntraday
        ? () => fetchIntraday().then((pts) => pts.map((p) => ({ time: p.time, value: p.net_worth_base_ccy })))
        : undefined,
    [fetchIntraday]
  );

  return (
    <RangeAreaChart
      points={rows}
      ranges={RANGES}
      currency={currency}
      height={height}
      growth={growth}
      formatValue={formatMoney}
      tooltipLabel="Net worth"
      gradientId="nwFill"
      emptyMessage="No history yet — add positions to start tracking your net worth over time."
      zeroBasedOnMax
      fetchIntraday={fetchHourly}
    />
  );
}
