import { BarChart, Bar, XAxis, YAxis, Tooltip, CartesianGrid, Legend, ResponsiveContainer } from "recharts";
import type { MonthlyFlow } from "../types";
import { formatMoney, formatPct } from "../lib/format";
import { useTheme } from "../context/ThemeContext";
import { usePalette } from "../context/PaletteContext";
import { getChartTheme } from "../lib/chartTheme";
import ResponsiveTable, { type ResponsiveColumn } from "./ResponsiveTable";

// Fixed, not taken from the accent palette: income and spending mean the
// same thing whichever accent is chosen. Checked with the dataviz palette
// validator against the app's own surfaces (#FFFFFF light, #131417 dark):
// lightness band, chroma, colour-blind separation and contrast all pass.
const SERIES = {
  light: { income: "#2954FF", expense: "#DC2626" },
  dark: { income: "#5B7BFF", expense: "#EF5A5A" },
};

function monthLabel(key: string): string {
  const [y, m] = key.split("-").map(Number);
  return new Date(y, m - 1, 1).toLocaleDateString("en-US", { month: "short", year: "2-digit" });
}

/**
 * Income next to spending, month by month, with what was left and the
 * savings rate in the table underneath -- two different measures, so two
 * views on one scale each, never a second axis on the chart.
 */
export default function MonthlyFlowChart({ rows, currency }: { rows: MonthlyFlow[]; currency: string }) {
  const { theme } = useTheme();
  const { palette } = usePalette();
  const chart = getChartTheme(theme === "dark", palette);
  const colors = theme === "dark" ? SERIES.dark : SERIES.light;
  const data = rows.map((r) => ({ ...r, label: monthLabel(r.month) }));

  return (
    <div className="space-y-4">
      <div className="h-64" role="img" aria-label="Monthly income and spending">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={data} barGap={2} barCategoryGap="22%" margin={{ top: 8, right: 8, left: 8, bottom: 0 }}>
            <CartesianGrid vertical={false} stroke={chart.grid} />
            <XAxis dataKey="label" tick={{ fill: chart.muted, fontSize: 11 }} axisLine={false} tickLine={false} />
            <YAxis
              tick={{ fill: chart.muted, fontSize: 11 }}
              axisLine={false}
              tickLine={false}
              width={64}
              tickFormatter={(v: number) => formatMoney(v, currency)}
            />
            <Tooltip
              cursor={{ fill: chart.grid, opacity: 0.4 }}
              contentStyle={{ background: chart.panelBg, border: `1px solid ${chart.grid}`, borderRadius: 6, fontSize: 12 }}
              labelStyle={{ color: chart.text }}
              formatter={(v: any, name: any) => [formatMoney(Number(v), currency), name]}
            />
            <Legend wrapperStyle={{ fontSize: 12, color: chart.text }} />
            <Bar dataKey="income" name="Income" fill={colors.income} radius={[4, 4, 0, 0]} maxBarSize={28} />
            <Bar dataKey="expense" name="Spending" fill={colors.expense} radius={[4, 4, 0, 0]} maxBarSize={28} />
          </BarChart>
        </ResponsiveContainer>
      </div>

      <ResponsiveTable
        keyFor={(r) => r.month}
        rows={[...rows].reverse()}
        columns={
          [
            { header: "Month", cell: (r) => monthLabel(r.month), className: "font-sans" },
            {
              header: "Income",
              className: "text-right num",
              headClassName: "text-right",
              cell: (r) => formatMoney(r.income, currency),
            },
            {
              header: "Spending",
              className: "text-right num",
              headClassName: "text-right",
              cell: (r) => formatMoney(r.expense, currency),
            },
            {
              header: "Left over",
              className: "text-right num",
              headClassName: "text-right",
              cell: (r) => <span className={r.net < 0 ? "text-loss" : ""}>{formatMoney(r.net, currency)}</span>,
            },
            {
              header: "Savings rate",
              className: "text-right num",
              headClassName: "text-right",
              cell: (r) =>
                r.savings_rate === null ? (
                  <span className="text-muted">—</span>
                ) : (
                  <span className={r.savings_rate < 0 ? "text-loss" : ""}>{formatPct(r.savings_rate)}</span>
                ),
            },
          ] as ResponsiveColumn<MonthlyFlow>[]
        }
      />
    </div>
  );
}
