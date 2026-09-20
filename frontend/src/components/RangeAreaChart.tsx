import { useMemo, useState, type ReactNode } from "react";
import { AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from "recharts";
import type { GrowthStats } from "../types";
import { formatDate, toLocalISODate } from "../lib/format";
import { useTheme } from "../context/ThemeContext";
import { usePalette } from "../context/PaletteContext";
import { getChartTheme } from "../lib/chartTheme";
import SegmentedControl from "./SegmentedControl";
import {
  type RangeKey,
  type DisplayMode,
  RANGE_LABELS,
  GROWTH_KEYS,
  cutoffFor,
  formatHour,
  formatPctTick,
  toPercentage,
  useIntradayData,
  GrowthBadge,
} from "./chartHelpers";

/** One dated point of the daily series. */
export interface SeriesPoint {
  date: string;
  value: number;
}

/** One hourly point of the intraday series. */
export interface HourlyPoint {
  time: string;
  value: number;
}

interface RangeAreaChartProps {
  points: SeriesPoint[];
  /** Which range buttons to offer, in order. */
  ranges: RangeKey[];
  currency: string;
  height: number;
  /** Day/week/month/year/max growth stats, shown next to the range control. */
  growth?: GrowthStats | null;
  /**
   * How a value is rendered in the Y axis, the tooltip and the growth badge.
   * NetWorthChart passes formatMoney and AssetPriceChart formatMoneyPrecise:
   * a real, deliberate difference (an aggregate total rounds to whole units,
   * a single asset's price needs decimals), which is why it's a prop.
   */
  formatValue: (value: number, currency: string) => string;
  /** Tooltip series name in absolute mode ("Net worth", "Price", ...). */
  tooltipLabel: string;
  /** Unique id for this chart's fill gradient, so two charts can't collide. */
  gradientId: string;
  /** Shown instead of the chart when there is no data at all. */
  emptyMessage: string;
  /**
   * Anchors the Y axis at zero on "Max" in absolute mode -- reads as "grown
   * from nothing", which suits a net-worth total but not an asset's price.
   * Every other combination auto-zooms to the visible data's own range, since
   * a small move on Day/Week barely registers against a zero-based axis.
   */
  zeroBasedOnMax?: boolean;
  /** If provided, "Day" fetches real hourly points through this instead. */
  fetchIntraday?: () => Promise<HourlyPoint[]>;
  /** Extra controls appended to the range row (e.g. an explanatory tooltip). */
  extraControls?: ReactNode;
}

/**
 * The range-selectable area chart behind both NetWorthChart and
 * AssetPriceChart: range/percentage controls, the growth badge, optional
 * real-hourly "Day" data, the empty states, and the chart itself. The two
 * callers were near-identical copies of all of it and now only describe what
 * genuinely differs (how a point maps to a value, how a value is formatted,
 * which ranges exist, whether the axis is zero-based).
 */
export default function RangeAreaChart({
  points,
  ranges,
  currency,
  height,
  growth,
  formatValue,
  tooltipLabel,
  gradientId,
  emptyMessage,
  zeroBasedOnMax = false,
  fetchIntraday,
  extraControls,
}: RangeAreaChartProps) {
  const { theme } = useTheme();
  const { palette } = usePalette();
  const chart = getChartTheme(theme === "dark", palette);
  const [range, setRange] = useState<RangeKey>("MAX");
  const [displayMode, setDisplayMode] = useState<DisplayMode>("absolute");
  const { intraday, loading: loadingIntraday } = useIntradayData<HourlyPoint>(range, fetchIntraday);

  const filteredPoints = useMemo(() => {
    const cutoff = cutoffFor(range);
    if (!cutoff) return points;
    // Compared as plain "YYYY-MM-DD" strings, which sort chronologically.
    // `new Date(p.date) >= cutoff` looked equivalent and wasn't: a bare
    // date string is parsed as UTC midnight while `cutoff` is a local Date
    // carrying the current time of day, so the boundary day fell in or out
    // depending on the viewer's timezone and what time it happened to be --
    // "Week" showing six days east of UTC, eight west of it. The same
    // mismatch formatDate/toLocalISODate already exist to avoid.
    const cutoffDay = toLocalISODate(cutoff);
    return points.filter((p) => p.date >= cutoffDay);
  }, [points, range]);

  const activeGrowth = growth ? growth[GROWTH_KEYS[range]] : null;

  const rangeControl = (
    <div className="flex items-center justify-between mb-2 flex-wrap gap-2">
      <GrowthBadge growth={activeGrowth} currency={currency} formatMoney={formatValue} />
      <div className="flex items-center gap-2 ml-auto flex-wrap">
        <SegmentedControl
          options={[
            { value: "absolute", label: currency === "EUR" ? "€" : currency },
            { value: "percentage", label: "%" },
          ]}
          value={displayMode}
          onChange={setDisplayMode}
        />
        <SegmentedControl
          options={ranges.map((r) => ({ value: r, label: RANGE_LABELS[r] }))}
          value={range}
          onChange={setRange}
        />
        {extraControls}
      </div>
    </div>
  );

  /** Every "no chart to draw" case renders the same frame, only the words differ. */
  const placeholder = (message: string, centered = false) => (
    <div>
      {rangeControl}
      <div
        className={`flex items-center justify-center text-muted text-sm${centered ? " text-center px-6" : ""}`}
        style={{ height: height - 32 }}
      >
        {message}
      </div>
    </div>
  );

  const usingIntraday = range === "D" && !!fetchIntraday;

  if (usingIntraday && loadingIntraday) return placeholder("Loading hourly prices…");
  if (usingIntraday && (!intraday || intraday.length === 0)) {
    return placeholder(
      "No hourly data for today yet — markets may be closed (weekend/holiday), or haven't opened yet.",
      true
    );
  }
  if (!usingIntraday && points.length === 0) {
    return (
      <div className="flex items-center justify-center text-muted text-sm" style={{ height }}>
        {emptyMessage}
      </div>
    );
  }
  if (!usingIntraday && filteredPoints.length === 0) return placeholder("No data in this range yet.");

  // Both series end up as {label, value}: an hour of today, or a tracked day.
  let rows = usingIntraday
    ? intraday!.map((p) => ({ label: formatHour(p.time), value: p.value }))
    : filteredPoints.map((p) => ({ label: formatDate(p.date), value: p.value }));
  if (displayMode === "percentage") rows = toPercentage(rows);

  const isPercentage = displayMode === "percentage";
  const fillId = usingIntraday ? `${gradientId}Hourly` : gradientId;
  const yDomain: [any, any] =
    zeroBasedOnMax && !isPercentage && range === "MAX" ? [0, "auto"] : ["auto", "auto"];

  return (
    <div>
      {rangeControl}
      <ResponsiveContainer width="100%" height={height - 32}>
        <AreaChart data={rows} margin={{ top: 8, right: 8, left: 8, bottom: 0 }}>
          <defs>
            <linearGradient id={fillId} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={chart.accent} stopOpacity={0.35} />
              <stop offset="100%" stopColor={chart.accent} stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid stroke={chart.grid} strokeDasharray="2 4" vertical={false} />
          <XAxis
            dataKey="label"
            tick={{ fill: chart.muted, fontSize: 11, fontFamily: "IBM Plex Mono" }}
            axisLine={{ stroke: chart.grid }}
            tickLine={false}
            minTickGap={40}
          />
          <YAxis
            tick={{ fill: chart.muted, fontSize: 11, fontFamily: "IBM Plex Mono" }}
            axisLine={false}
            tickLine={false}
            width={70}
            tickFormatter={isPercentage ? formatPctTick : (v: number) => formatValue(v, currency)}
            domain={yDomain}
          />
          <Tooltip
            contentStyle={{
              background: chart.panelBg,
              border: `1px solid ${chart.grid}`,
              borderRadius: 6,
              fontFamily: "IBM Plex Mono",
              fontSize: 12,
            }}
            labelStyle={{ color: chart.muted }}
            formatter={(v: any) =>
              isPercentage
                ? [formatPctTick(Number(v)), "Change"]
                : [formatValue(Number(v), currency), tooltipLabel]
            }
          />
          <Area type="monotone" dataKey="value" stroke={chart.accent} strokeWidth={2} fill={`url(#${fillId})`} />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}
