import { useEffect, useMemo, useState } from "react";
import type { NetWorthPoint, GrowthStats, IntradayPoint } from "../types";
import { formatDate, formatMoney } from "../lib/format";
import { useTheme } from "../context/ThemeContext";
import { getChartTheme } from "../lib/chartTheme";
import type { RangeKey, DisplayMode } from "../lib/timeSeriesChart";
import {
  RANGE_LABELS, GROWTH_KEYS,
  cutoffFor, formatHour, formatPctTick, toPercentage,
} from "../lib/timeSeriesChart";
import { AreaTimeSeriesChart } from "./TimeSeriesChart";

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
  const { theme } = useTheme();
  const chart = getChartTheme(theme === "dark");
  const [range, setRange] = useState<RangeKey>("MAX");
  const [displayMode, setDisplayMode] = useState<DisplayMode>("absolute");
  const [intraday, setIntraday] = useState<IntradayPoint[] | null>(null);
  const [loadingIntraday, setLoadingIntraday] = useState(false);

  useEffect(() => {
    if (range !== "D" || !fetchIntraday) {
      setIntraday(null);
      return;
    }
    let cancelled = false;
    setLoadingIntraday(true);
    fetchIntraday()
      .then((pts) => {
        if (!cancelled) setIntraday(pts);
      })
      .catch(() => {
        if (!cancelled) setIntraday([]);
      })
      .finally(() => {
        if (!cancelled) setLoadingIntraday(false);
      });
    return () => {
      cancelled = true;
    };
  }, [range, fetchIntraday]);

  const filteredPoints = useMemo(() => {
    const cutoff = cutoffFor(range);
    if (!cutoff) return points;
    return points.filter((p) => new Date(p.date) >= cutoff);
  }, [points, range]);

  const activeGrowth = growth ? growth[GROWTH_KEYS[range]] : null;

  const growthDisplay = activeGrowth ? (
    <div className="text-sm">
      <span className={activeGrowth.change >= 0 ? "text-gain" : "text-loss"}>
        {activeGrowth.change >= 0 ? "+" : ""}
        {formatMoney(activeGrowth.change, currency)}
        {activeGrowth.change_pct !== null && (
          <> ({activeGrowth.change >= 0 ? "+" : ""}{activeGrowth.change_pct.toFixed(1)}%)</>
        )}
      </span>
      <span className="text-muted ml-1.5">since {formatDate(activeGrowth.start_date)}</span>
    </div>
  ) : (
    <div />
  );

  const rangeControl = (
    <div className="flex items-center justify-between mb-2 flex-wrap gap-2">
      {growthDisplay}
      <div className="flex items-center gap-2 ml-auto">
        <div className="flex rounded border ledger-rule overflow-hidden text-xs shrink-0">
          {(["absolute", "percentage"] as DisplayMode[]).map((m) => (
            <button
              key={m}
              onClick={() => setDisplayMode(m)}
              className={`px-2.5 py-1 transition-colors ${
                displayMode === m ? "bg-brass text-ink font-medium" : "text-muted hover:bg-ink-raised"
              }`}
            >
              {m === "absolute" ? currency === "EUR" ? "€" : currency : "%"}
            </button>
          ))}
        </div>
        <div className="flex rounded border ledger-rule overflow-hidden text-xs shrink-0">
          {(["D", "W", "M", "Y", "MAX"] as RangeKey[]).map((r) => (
            <button
              key={r}
              onClick={() => setRange(r)}
              className={`px-3 py-1 transition-colors ${
                range === r ? "bg-brass text-ink font-medium" : "text-muted hover:bg-ink-raised"
              }`}
            >
              {RANGE_LABELS[r]}
            </button>
          ))}
        </div>
      </div>
    </div>
  );

  const usingIntraday = range === "D" && !!fetchIntraday;
  const yTickFormatter = displayMode === "percentage" ? formatPctTick : (v: number) => formatMoney(v, currency);
  const tooltipLabel = displayMode === "percentage" ? "Change" : "Net worth";
  const tooltipFormatter = (v: unknown) =>
    displayMode === "percentage"
      ? ([formatPctTick(Number(v)), tooltipLabel] as [string, string])
      : ([formatMoney(Number(v), currency), tooltipLabel] as [string, string]);
  // Only the absolute view on "Max" stays anchored to zero (a deliberate
  // choice: it should read as "grown from nothing"). Every other
  // combination auto-zooms to the visible data's own range, since a small
  // move on Day/Week barely registers against a Max-sized, zero-based axis.
  // This behavior is specific to the net worth chart -- AssetPriceChart
  // always auto-zooms, even on Max.
  const yDomain: [any, any] = displayMode === "absolute" && range === "MAX" ? [0, "auto"] : ["auto", "auto"];

  if (usingIntraday) {
    if (loadingIntraday) {
      return (
        <div>
          {rangeControl}
          <div className="flex items-center justify-center text-muted text-sm" style={{ height: height - 32 }}>
            Loading hourly prices…
          </div>
        </div>
      );
    }
    if (!intraday || intraday.length === 0) {
      return (
        <div>
          {rangeControl}
          <div className="flex items-center justify-center text-muted text-sm text-center px-6" style={{ height: height - 32 }}>
            No hourly data for today yet — markets may be closed (weekend/holiday), or haven't
            opened yet.
          </div>
        </div>
      );
    }

    let hourRows = intraday.map((p) => ({ time: p.time, value: p.net_worth_base_ccy }));
    if (displayMode === "percentage") hourRows = toPercentage(hourRows);
    const hourData = hourRows.map((r) => ({ ...r, timeLabel: formatHour(r.time) }));

    return (
      <div>
        {rangeControl}
        <AreaTimeSeriesChart
          data={hourData}
          xKey="timeLabel"
          gradientId="nwFillHourly"
          chart={chart}
          height={height - 32}
          yTickFormatter={yTickFormatter}
          tooltipFormatter={tooltipFormatter}
          yDomain={yDomain}
        />
      </div>
    );
  }

  if (points.length === 0) {
    return (
      <div className="flex items-center justify-center text-muted text-sm" style={{ height }}>
        No history yet — add positions to start tracking your net worth over time.
      </div>
    );
  }

  if (filteredPoints.length === 0) {
    return (
      <div>
        {rangeControl}
        <div className="flex items-center justify-center text-muted text-sm" style={{ height: height - 32 }}>
          No data in this range yet.
        </div>
      </div>
    );
  }

  let rows = filteredPoints.map((p) => ({ date: p.date, value: p.net_worth_base_ccy }));
  if (displayMode === "percentage") rows = toPercentage(rows);
  const data = rows.map((r) => ({ ...r, dateLabel: formatDate(r.date) }));

  return (
    <div>
      {rangeControl}
      <AreaTimeSeriesChart
        data={data}
        xKey="dateLabel"
        gradientId="nwFill"
        chart={chart}
        height={height - 32}
        yTickFormatter={yTickFormatter}
        tooltipFormatter={tooltipFormatter}
        yDomain={yDomain}
      />
    </div>
  );
}
