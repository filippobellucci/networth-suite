import { AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from "recharts";
import type { ChartTheme } from "../lib/chartTheme";

/**
 * Shared Recharts rendering for the D/W/M/Y/Max area-chart pattern used by
 * both NetWorthChart and AssetPriceChart. Previously each file duplicated
 * this ~100-line JSX block almost verbatim (twice each, once for the daily
 * view and once for the hourly "Day" view) -- any fix to one had to be
 * repeated by hand in the other three copies. Extracted here so there's a
 * single place to change; range/formatting helpers live alongside this in
 * lib/timeSeriesChart.ts. The two call sites only differ in which field
 * they plot, how they format money, and a couple of deliberately different
 * behaviors called out where they occur (see NetWorthChart/AssetPriceChart).
 */

/** The actual Recharts rendering, identical between net worth and asset price
 * charts -- only the data rows, x-axis key, gradient id, Y domain, and
 * formatters differ, all passed in as props. */
export function AreaTimeSeriesChart({
  data,
  xKey,
  gradientId,
  chart,
  height,
  yTickFormatter,
  tooltipFormatter,
  yDomain,
}: {
  data: Array<Record<string, unknown>>;
  xKey: string;
  gradientId: string;
  chart: ChartTheme;
  height: number;
  yTickFormatter: (v: number) => string;
  tooltipFormatter: (v: unknown) => [string, string];
  // eslint-disable-next-line @typescript-eslint/no-explicit-any -- matches recharts' own AxisDomain typing, same as before this was extracted
  yDomain: [any, any];
}) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <AreaChart data={data} margin={{ top: 8, right: 8, left: 8, bottom: 0 }}>
        <defs>
          <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={chart.accent} stopOpacity={0.35} />
            <stop offset="100%" stopColor={chart.accent} stopOpacity={0} />
          </linearGradient>
        </defs>
        <CartesianGrid stroke={chart.grid} strokeDasharray="2 4" vertical={false} />
        <XAxis
          dataKey={xKey}
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
          formatter={tooltipFormatter}
        />
        <Area type="monotone" dataKey="value" stroke={chart.accent} strokeWidth={2} fill={`url(#${gradientId})`} />
      </AreaChart>
    </ResponsiveContainer>
  );
}
