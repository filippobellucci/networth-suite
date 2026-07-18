import { AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from "recharts";
import type { NetWorthPoint } from "../types";
import { formatDate, formatMoney } from "../lib/format";

export default function NetWorthChart({
  points,
  currency = "EUR",
  height = 260,
}: {
  points: NetWorthPoint[];
  currency?: string;
  height?: number;
}) {
  if (points.length === 0) {
    return (
      <div className="flex items-center justify-center text-muted text-sm" style={{ height }}>
        No history yet — add positions to start tracking your net worth over time.
      </div>
    );
  }

  const data = points.map((p) => ({ ...p, dateLabel: formatDate(p.date) }));

  return (
    <ResponsiveContainer width="100%" height={height}>
      <AreaChart data={data} margin={{ top: 8, right: 8, left: 8, bottom: 0 }}>
        <defs>
          <linearGradient id="nwFill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#C8A661" stopOpacity={0.35} />
            <stop offset="100%" stopColor="#C8A661" stopOpacity={0} />
          </linearGradient>
        </defs>
        <CartesianGrid stroke="#2A3937" strokeDasharray="2 4" vertical={false} />
        <XAxis
          dataKey="dateLabel"
          tick={{ fill: "#8CA39C", fontSize: 11, fontFamily: "IBM Plex Mono" }}
          axisLine={{ stroke: "#2A3937" }}
          tickLine={false}
          minTickGap={40}
        />
        <YAxis
          tick={{ fill: "#8CA39C", fontSize: 11, fontFamily: "IBM Plex Mono" }}
          axisLine={false}
          tickLine={false}
          width={70}
          tickFormatter={(v) => formatMoney(v, currency)}
        />
        <Tooltip
          contentStyle={{
            background: "#1A2624",
            border: "1px solid #2A3937",
            borderRadius: 6,
            fontFamily: "IBM Plex Mono",
            fontSize: 12,
          }}
          labelStyle={{ color: "#8CA39C" }}
          formatter={(v: any) => [formatMoney(Number(v), currency), "Net worth"]}
        />
        <Area
          type="monotone"
          dataKey="net_worth_base_ccy"
          stroke="#C8A661"
          strokeWidth={2}
          fill="url(#nwFill)"
        />
      </AreaChart>
    </ResponsiveContainer>
  );
}
