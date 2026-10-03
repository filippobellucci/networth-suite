import type { ReactNode } from "react";
import { PieChart, Pie, Cell, Tooltip, ResponsiveContainer } from "recharts";
import type { CashPosition, HoldingPosition } from "../types";
import { formatMoney, formatPct } from "../lib/format";
import { usePortfolioPicker, usePortfolioSnapshot } from "../hooks/usePortfolioData";
import { useTheme } from "../context/ThemeContext";
import { usePalette } from "../context/PaletteContext";
import { getChartTheme, type ChartTheme } from "../lib/chartTheme";
import InfoTooltip from "./InfoTooltip";
import ResponsiveTable, { type ResponsiveColumn } from "./ResponsiveTable";

interface Slice {
  key: string;
  label: string;
  value: number;
  pct: number;
}

/**
 * One portfolio's current value split into groups -- by currency, by
 * allocation category -- behind a portfolio picker: a donut chart and the
 * same figures as a table. The pages using it only say which group each
 * position and cash balance falls into, and how a group is named and coloured.
 */
export default function SnapshotBreakdown({
  info,
  emptyMessage,
  groupHeader,
  positionGroup,
  cashGroup,
  labelOf = (key) => key,
  colorOf,
}: {
  /** What the breakdown measures, shown in the heading's tooltip. */
  info: ReactNode;
  emptyMessage: ReactNode;
  /** Header of the table's first column. */
  groupHeader: string;
  positionGroup: (p: HoldingPosition) => string;
  cashGroup: (c: CashPosition) => string;
  labelOf?: (key: string) => string;
  /** `index` is the slice's position once sorted, largest first. */
  colorOf: (key: string, index: number, chart: ChartTheme) => string;
}) {
  const { theme } = useTheme();
  const { palette } = usePalette();
  const chart = getChartTheme(theme === "dark", palette);
  const { portfolios, selectedPortfolio, setSelectedPortfolio, loading, error } = usePortfolioPicker();
  const snapshot = usePortfolioSnapshot(selectedPortfolio);

  const slices: Slice[] = [];
  if (snapshot) {
    const totals: Record<string, number> = {};
    for (const p of snapshot.positions) {
      if (!p.value_base_ccy) continue;
      const key = positionGroup(p);
      totals[key] = (totals[key] ?? 0) + p.value_base_ccy;
    }
    for (const c of snapshot.cash_positions) {
      const key = cashGroup(c);
      totals[key] = (totals[key] ?? 0) + c.value_base_ccy;
    }
    const total = Object.values(totals).reduce((s, v) => s + v, 0);
    for (const [key, value] of Object.entries(totals)) {
      slices.push({ key, label: labelOf(key), value, pct: total ? (value / total) * 100 : 0 });
    }
    slices.sort((a, b) => b.value - a.value);
  }
  const color = (s: Slice) => colorOf(s.key, slices.indexOf(s), chart);

  return (
    <div className="space-y-8">
      <div className="card p-6">
        <div className="flex items-center justify-between mb-4">
          <h2 className="font-display text-lg flex items-center gap-2">
            Breakdown
            <InfoTooltip>{info}</InfoTooltip>
          </h2>
          <select className="input" value={selectedPortfolio} onChange={(e) => setSelectedPortfolio(e.target.value)}>
            {portfolios.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
        </div>

        {error && <p className="text-loss text-sm">{error}</p>}
        {loading ? (
          <p className="text-muted text-sm">Loading…</p>
        ) : !snapshot || slices.length === 0 ? (
          <p className="text-muted text-sm">{emptyMessage}</p>
        ) : (
          <div className="flex flex-col md:flex-row items-center gap-6">
            <ResponsiveContainer width="100%" height={320} className="md:max-w-sm">
              <PieChart>
                <Pie
                  data={slices}
                  dataKey="value"
                  nameKey="label"
                  innerRadius={60}
                  outerRadius={120}
                  paddingAngle={1}
                  stroke={chart.panelBg}
                  strokeWidth={2}
                >
                  {slices.map((s) => (
                    <Cell key={s.key} fill={color(s)} />
                  ))}
                </Pie>
                <Tooltip
                  contentStyle={{ background: chart.panelBg, border: `1px solid ${chart.grid}`, borderRadius: 6, fontSize: 12 }}
                  formatter={(v: any, _name: any, item: any) => [
                    formatMoney(Number(v), snapshot.base_currency),
                    item?.payload?.label,
                  ]}
                />
              </PieChart>
            </ResponsiveContainer>

            <div className="flex-1 w-full">
              <ResponsiveTable
                keyFor={(s) => s.key}
                rows={slices}
                columns={
                  [
                    {
                      header: groupHeader,
                      cell: (s) => (
                        <>
                          <span
                            className="inline-block w-2.5 h-2.5 rounded-full mr-2 align-middle"
                            style={{ backgroundColor: color(s) }}
                          />
                          {s.label}
                        </>
                      ),
                    },
                    {
                      header: "Value",
                      className: "text-right font-mono num",
                      headClassName: "text-right",
                      cell: (s) => formatMoney(s.value, snapshot.base_currency),
                    },
                    {
                      header: "Share",
                      className: "text-right font-mono num text-muted",
                      headClassName: "text-right",
                      cell: (s) => formatPct(s.pct),
                    },
                  ] as ResponsiveColumn<Slice>[]
                }
              />
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
