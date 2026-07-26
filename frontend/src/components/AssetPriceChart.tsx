import { useEffect, useMemo, useState } from "react";
import type { AssetPricePoint, AssetIntradayPoint, GrowthStats } from "../types";
import { formatDate, formatMoney } from "../lib/format";
import { useTheme } from "../context/ThemeContext";
import { getChartTheme } from "../lib/chartTheme";
import InfoTooltip from "./InfoTooltip";
import type { RangeKey, DisplayMode } from "../lib/timeSeriesChart";
import {
  RANGE_LABELS, GROWTH_KEYS,
  cutoffFor, formatHour, formatPctTick, toPercentage,
} from "../lib/timeSeriesChart";
import { AreaTimeSeriesChart } from "./TimeSeriesChart";

export default function AssetPriceChart({
  points,
  currency = "EUR",
  height = 260,
  growth,
  fetchIntraday,
}: {
  points: AssetPricePoint[];
  currency?: string;
  height?: number;
  growth?: GrowthStats | null;
  /** Only provided for ticker-based assets -- manual-priced ones have no hourly data. */
  fetchIntraday?: () => Promise<AssetIntradayPoint[]>;
}) {
  const { theme } = useTheme();
  const chart = getChartTheme(theme === "dark");
  const [range, setRange] = useState<RangeKey>("MAX");
  const [displayMode, setDisplayMode] = useState<DisplayMode>("absolute");
  const [intraday, setIntraday] = useState<AssetIntradayPoint[] | null>(null);
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

  const ranges: RangeKey[] = fetchIntraday ? ["D", "W", "M", "Y", "MAX"] : ["W", "M", "Y", "MAX"];

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
              {m === "absolute" ? (currency === "EUR" ? "€" : currency) : "%"}
            </button>
          ))}
        </div>
        <div className="flex rounded border ledger-rule overflow-hidden text-xs shrink-0">
          {ranges.map((r) => (
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
        {!fetchIntraday && (
          <InfoTooltip>
            <p>
              There's no "Day" view for this asset because it has no ticker — its price only
              changes when you enter a new manual price by hand, so there's no hourly data that
              could exist to show.
            </p>
          </InfoTooltip>
        )}
      </div>
    </div>
  );

  const usingIntraday = range === "D" && !!fetchIntraday;
  const yTickFormatter = displayMode === "percentage" ? formatPctTick : (v: number) => formatMoney(v, currency);
  const tooltipLabel = displayMode === "percentage" ? "Change" : "Price";
  const tooltipFormatter = (v: unknown) =>
    displayMode === "percentage"
      ? ([formatPctTick(Number(v)), tooltipLabel] as [string, string])
      : ([formatMoney(Number(v), currency), tooltipLabel] as [string, string]);
  // Unlike NetWorthChart, the asset price chart always auto-zooms -- there's
  // no "grown from nothing" zero-anchoring on Max here, on purpose (that's a
  // net-worth-specific reading, not a price-specific one).
  const yDomain: [any, any] = ["auto", "auto"];

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

    let hourRows = intraday.map((p) => ({ time: p.time, value: p.price }));
    if (displayMode === "percentage") hourRows = toPercentage(hourRows);
    const hourData = hourRows.map((r) => ({ ...r, timeLabel: formatHour(r.time) }));

    return (
      <div>
        {rangeControl}
        <AreaTimeSeriesChart
          data={hourData}
          xKey="timeLabel"
          gradientId="assetFillHourly"
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
        No price history yet.
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

  let rows = filteredPoints.map((p) => ({ date: p.date, value: p.price }));
  if (displayMode === "percentage") rows = toPercentage(rows);
  const data = rows.map((r) => ({ ...r, dateLabel: formatDate(r.date) }));

  return (
    <div>
      {rangeControl}
      <AreaTimeSeriesChart
        data={data}
        xKey="dateLabel"
        gradientId="assetFill"
        chart={chart}
        height={height - 32}
        yTickFormatter={yTickFormatter}
        tooltipFormatter={tooltipFormatter}
        yDomain={yDomain}
      />
    </div>
  );
}
