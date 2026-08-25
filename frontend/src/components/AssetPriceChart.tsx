import { useEffect, useMemo, useState } from "react";
import { AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from "recharts";
import type { AssetPricePoint, AssetIntradayPoint, GrowthStats } from "../types";
import { formatDate, formatMoneyPrecise } from "../lib/format";
import { useTheme } from "../context/ThemeContext";
import { getChartTheme } from "../lib/chartTheme";
import InfoTooltip from "./InfoTooltip";
import SegmentedControl from "./SegmentedControl";

type RangeKey = "D" | "W" | "M" | "Y" | "MAX";
type DisplayMode = "absolute" | "percentage";

const RANGE_LABELS: Record<RangeKey, string> = { D: "Day", W: "Week", M: "Month", Y: "Year", MAX: "Max" };
const GROWTH_KEYS: Record<RangeKey, keyof Omit<GrowthStats, "current">> = {
  D: "day",
  W: "week",
  M: "month",
  Y: "year",
  MAX: "max",
};

function cutoffFor(range: RangeKey): Date | null {
  if (range === "MAX") return null;
  const d = new Date();
  if (range === "D") d.setDate(d.getDate() - 1);
  if (range === "W") d.setDate(d.getDate() - 7);
  if (range === "M") d.setMonth(d.getMonth() - 1);
  if (range === "Y") d.setFullYear(d.getFullYear() - 1);
  return d;
}

function formatHour(iso: string): string {
  return new Date(iso).toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit" });
}

function formatPctTick(v: number): string {
  return `${v >= 0 ? "+" : ""}${v.toFixed(1)}%`;
}

function toPercentage<T extends { value: number }>(rows: T[]): T[] {
  if (rows.length === 0) return rows;
  const base = rows[0].value;
  if (!base) return rows.map((r) => ({ ...r, value: 0 }));
  return rows.map((r) => ({ ...r, value: ((r.value - base) / base) * 100 }));
}

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
        {formatMoneyPrecise(activeGrowth.change, currency)}
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
  const yTickFormatter = displayMode === "percentage" ? formatPctTick : (v: number) => formatMoneyPrecise(v, currency);
  const tooltipLabel = displayMode === "percentage" ? "Change" : "Price";
  const tooltipFormatter = (v: any) =>
    displayMode === "percentage" ? [formatPctTick(Number(v)), tooltipLabel] : [formatMoneyPrecise(Number(v), currency), tooltipLabel];

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
        <ResponsiveContainer width="100%" height={height - 32}>
          <AreaChart data={hourData} margin={{ top: 8, right: 8, left: 8, bottom: 0 }}>
            <defs>
              <linearGradient id="assetFillHourly" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={chart.accent} stopOpacity={0.35} />
                <stop offset="100%" stopColor={chart.accent} stopOpacity={0} />
              </linearGradient>
            </defs>
            <CartesianGrid stroke={chart.grid} strokeDasharray="2 4" vertical={false} />
            <XAxis
              dataKey="timeLabel"
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
              tickFormatter={yTickFormatter}
              domain={["auto", "auto"]}
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
              formatter={tooltipFormatter}
            />
            <Area type="monotone" dataKey="value" stroke={chart.accent} strokeWidth={2} fill="url(#assetFillHourly)" />
          </AreaChart>
        </ResponsiveContainer>
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
      <ResponsiveContainer width="100%" height={height - 32}>
        <AreaChart data={data} margin={{ top: 8, right: 8, left: 8, bottom: 0 }}>
          <defs>
            <linearGradient id="assetFill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={chart.accent} stopOpacity={0.35} />
              <stop offset="100%" stopColor={chart.accent} stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid stroke={chart.grid} strokeDasharray="2 4" vertical={false} />
          <XAxis
            dataKey="dateLabel"
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
            tickFormatter={yTickFormatter}
            domain={["auto", "auto"]}
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
            formatter={tooltipFormatter}
          />
          <Area type="monotone" dataKey="value" stroke={chart.accent} strokeWidth={2} fill="url(#assetFill)" />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}
