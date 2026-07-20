import { useEffect, useMemo, useState } from "react";
import { AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from "recharts";
import type { NetWorthPoint, GrowthStats, IntradayPoint } from "../types";
import { formatDate, formatMoney } from "../lib/format";
import { useTheme } from "../context/ThemeContext";
import { getChartTheme } from "../lib/chartTheme";

type RangeKey = "D" | "W" | "M" | "Y" | "MAX";

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
      <div className="flex rounded border ledger-rule overflow-hidden text-xs shrink-0 ml-auto">
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
  );

  const usingIntraday = range === "D" && !!fetchIntraday;

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

    const hourData = intraday.map((p) => ({ ...p, timeLabel: formatHour(p.time) }));
    return (
      <div>
        {rangeControl}
        <ResponsiveContainer width="100%" height={height - 32}>
          <AreaChart data={hourData} margin={{ top: 8, right: 8, left: 8, bottom: 0 }}>
            <defs>
              <linearGradient id="nwFillHourly" x1="0" y1="0" x2="0" y2="1">
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
              tickFormatter={(v) => formatMoney(v, currency)}
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
              formatter={(v: any) => [formatMoney(Number(v), currency), "Net worth"]}
            />
            <Area
              type="monotone"
              dataKey="net_worth_base_ccy"
              stroke={chart.accent}
              strokeWidth={2}
              fill="url(#nwFillHourly)"
            />
          </AreaChart>
        </ResponsiveContainer>
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

  const data = filteredPoints.map((p) => ({ ...p, dateLabel: formatDate(p.date) }));

  return (
    <div>
      {rangeControl}
      <ResponsiveContainer width="100%" height={height - 32}>
        <AreaChart data={data} margin={{ top: 8, right: 8, left: 8, bottom: 0 }}>
          <defs>
            <linearGradient id="nwFill" x1="0" y1="0" x2="0" y2="1">
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
            tickFormatter={(v) => formatMoney(v, currency)}
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
            formatter={(v: any) => [formatMoney(Number(v), currency), "Net worth"]}
          />
          <Area
            type="monotone"
            dataKey="net_worth_base_ccy"
            stroke={chart.accent}
            strokeWidth={2}
            fill="url(#nwFill)"
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}
