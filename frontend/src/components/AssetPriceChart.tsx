import { useMemo, useState } from "react";
import { AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from "recharts";
import type { AssetPricePoint, AssetIntradayPoint, GrowthStats } from "../types";
import { formatDate, formatMoneyPrecise } from "../lib/format";
import { useTheme } from "../context/ThemeContext";
import { usePalette } from "../context/PaletteContext";
import { getChartTheme } from "../lib/chartTheme";
import InfoTooltip from "./InfoTooltip";
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
  const { palette } = usePalette();
  const chart = getChartTheme(theme === "dark", palette);
  const [range, setRange] = useState<RangeKey>("MAX");
  const [displayMode, setDisplayMode] = useState<DisplayMode>("absolute");
  const { intraday, loading: loadingIntraday } = useIntradayData<AssetIntradayPoint>(range, fetchIntraday);

  const filteredPoints = useMemo(() => {
    const cutoff = cutoffFor(range);
    if (!cutoff) return points;
    return points.filter((p) => new Date(p.date) >= cutoff);
  }, [points, range]);

  const activeGrowth = growth ? growth[GROWTH_KEYS[range]] : null;

  const growthDisplay = <GrowthBadge growth={activeGrowth} currency={currency} formatMoney={formatMoneyPrecise} />;


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
