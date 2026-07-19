import { useMemo, useState } from "react";
import { AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from "recharts";
import type { NetWorthPoint } from "../types";
import { formatDate, formatMoney } from "../lib/format";

type RangeKey = "D" | "M" | "Y" | "MAX";

const RANGE_LABELS: Record<RangeKey, string> = { D: "Day", M: "Month", Y: "Year", MAX: "Max" };

function cutoffFor(range: RangeKey): Date | null {
  if (range === "MAX") return null;
  const d = new Date();
  if (range === "D") d.setDate(d.getDate() - 1);
  if (range === "M") d.setMonth(d.getMonth() - 1);
  if (range === "Y") d.setFullYear(d.getFullYear() - 1);
  return d;
}

export default function NetWorthChart({
  points,
  currency = "EUR",
  height = 260,
}: {
  points: NetWorthPoint[];
  currency?: string;
  height?: number;
}) {
  const [range, setRange] = useState<RangeKey>("MAX");

  const filteredPoints = useMemo(() => {
    const cutoff = cutoffFor(range);
    if (!cutoff) return points;
    return points.filter((p) => new Date(p.date) >= cutoff);
  }, [points, range]);

  const rangeControl = (
    <div className="flex justify-end mb-2">
      <div className="flex rounded border ledger-rule overflow-hidden text-xs">
        {(["D", "M", "Y", "MAX"] as RangeKey[]).map((r) => (
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
              <stop offset="0%" stopColor="#6B4E14" stopOpacity={0.35} />
              <stop offset="100%" stopColor="#6B4E14" stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid stroke="#C7B78D" strokeDasharray="2 4" vertical={false} />
          <XAxis
            dataKey="dateLabel"
            tick={{ fill: "#75694C", fontSize: 11, fontFamily: "IBM Plex Mono" }}
            axisLine={{ stroke: "#C7B78D" }}
            tickLine={false}
            minTickGap={40}
          />
          <YAxis
            tick={{ fill: "#75694C", fontSize: 11, fontFamily: "IBM Plex Mono" }}
            axisLine={false}
            tickLine={false}
            width={70}
            tickFormatter={(v) => formatMoney(v, currency)}
          />
          <Tooltip
            contentStyle={{
              background: "#DCCDAE",
              border: "1px solid #C7B78D",
              borderRadius: 6,
              fontFamily: "IBM Plex Mono",
              fontSize: 12,
            }}
            labelStyle={{ color: "#75694C" }}
            formatter={(v: any) => [formatMoney(Number(v), currency), "Net worth"]}
          />
          <Area
            type="monotone"
            dataKey="net_worth_base_ccy"
            stroke="#6B4E14"
            strokeWidth={2}
            fill="url(#nwFill)"
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}
