import { useEffect, useState, useCallback } from "react";
import { PieChart, Pie, Cell, Tooltip, ResponsiveContainer } from "recharts";
import { api } from "../api/client";
import type { Portfolio, PortfolioSnapshot, AllocationCategory } from "../types";
import { ALLOCATION_CATEGORY_LABELS } from "../types";
import { formatMoney, formatPct } from "../lib/format";
import { useTheme } from "../context/ThemeContext";
import { getChartTheme } from "../lib/chartTheme";

type CategoryKey = AllocationCategory | "UNCATEGORIZED";

const CATEGORY_LABELS: Record<CategoryKey, string> = {
  ...ALLOCATION_CATEGORY_LABELS,
  UNCATEGORIZED: "Uncategorized",
};

const CATEGORY_COLORS_LIGHT: Record<CategoryKey, string> = {
  STOCK: "#6B4E14",
  BOND: "#2F6B4A",
  CASH: "#3E5F73",
  EMERGENCY_FUND: "#9C4A2E",
  PENSION_FUND: "#6B4E82",
  UNCATEGORIZED: "#75694C",
};

const CATEGORY_COLORS_DARK: Record<CategoryKey, string> = {
  STOCK: "#E3AC4E",
  BOND: "#5FA87D",
  CASH: "#6E93B0",
  EMERGENCY_FUND: "#D97C54",
  PENSION_FUND: "#A98BC4",
  UNCATEGORIZED: "#9C9080",
};

interface Slice {
  key: CategoryKey;
  label: string;
  value: number;
  pct: number;
}

export default function PortfolioAllocation() {
  const { theme } = useTheme();
  const chart = getChartTheme(theme === "dark");
  const CATEGORY_COLORS = theme === "dark" ? CATEGORY_COLORS_DARK : CATEGORY_COLORS_LIGHT;
  const [portfolios, setPortfolios] = useState<Portfolio[]>([]);
  const [selectedPortfolio, setSelectedPortfolio] = useState<string>("");
  const [snapshot, setSnapshot] = useState<PortfolioSnapshot | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(() => {
    setLoading(true);
    api
      .listPortfolios()
      .then((list) => {
        setPortfolios(list);
        if (!selectedPortfolio && list.length > 0) setSelectedPortfolio(list[0].id);
      })
      .catch((e) => setError(String(e.message || e)))
      .finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(reload, [reload]);

  useEffect(() => {
    if (!selectedPortfolio) return;
    api.getSnapshot(selectedPortfolio).then(setSnapshot).catch(() => setSnapshot(null));
  }, [selectedPortfolio]);

  const slices: Slice[] = [];
  if (snapshot) {
    const totals: Partial<Record<CategoryKey, number>> = {};
    for (const p of snapshot.positions) {
      if (!p.value_base_ccy) continue;
      const key: CategoryKey = p.category ?? "UNCATEGORIZED";
      totals[key] = (totals[key] ?? 0) + p.value_base_ccy;
    }
    for (const c of snapshot.cash_positions) {
      totals[c.category] = (totals[c.category] ?? 0) + c.value_base_ccy;
    }
    const total = Object.values(totals).reduce((s, v) => s + (v ?? 0), 0);
    for (const [key, value] of Object.entries(totals) as [CategoryKey, number][]) {
      slices.push({ key, label: CATEGORY_LABELS[key], value, pct: total ? (value / total) * 100 : 0 });
    }
    slices.sort((a, b) => b.value - a.value);
  }

  return (
    <div className="space-y-8">
      <div>
        <h1 className="font-display text-2xl mb-1">Portfolio Allocation</h1>
        <p className="text-muted text-sm">
          How much of this portfolio sits in stocks, bonds, cash, the emergency fund, and the
          pension fund — tagged per position and per balance.
        </p>
      </div>

      <div className="card p-6">
        <div className="flex items-center justify-between mb-4">
          <h2 className="font-display text-lg">Breakdown</h2>
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
          <p className="text-muted text-sm">
            No tagged positions or balances yet in this portfolio. Add a tag from the Asset
            Catalogue, or add a Cash / Emergency Fund / Pension Fund balance from the portfolio
            page.
          </p>
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
                    <Cell key={s.key} fill={CATEGORY_COLORS[s.key]} />
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
              <table className="w-full text-sm">
                <tbody>
                  {slices.map((s) => (
                    <tr key={s.key} className="border-b ledger-rule last:border-0">
                      <td className="py-2 pr-3">
                        <span
                          className="inline-block w-2.5 h-2.5 rounded-full mr-2 align-middle"
                          style={{ backgroundColor: CATEGORY_COLORS[s.key] }}
                        />
                        {s.label}
                      </td>
                      <td className="py-2 text-right font-mono num">{formatMoney(s.value, snapshot.base_currency)}</td>
                      <td className="py-2 pl-3 text-right font-mono num text-muted w-16">{formatPct(s.pct)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
