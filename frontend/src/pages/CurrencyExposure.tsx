import { useEffect, useState, useCallback } from "react";
import { PieChart, Pie, Cell, Tooltip, ResponsiveContainer } from "recharts";
import { api } from "../api/client";
import type { Portfolio, PortfolioSnapshot } from "../types";
import { formatMoney, formatPct } from "../lib/format";
import { useTheme } from "../context/ThemeContext";
import { getChartTheme } from "../lib/chartTheme";
import InfoTooltip from "../components/InfoTooltip";
import ResponsiveTable, { type ResponsiveColumn } from "../components/ResponsiveTable";

interface Slice {
  currency: string;
  value: number;
  pct: number;
}

export default function CurrencyExposure() {
  const { theme } = useTheme();
  const chart = getChartTheme(theme === "dark");
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
    const totals: Record<string, number> = {};
    for (const p of snapshot.positions) {
      if (!p.value_base_ccy) continue;
      totals[p.price_currency] = (totals[p.price_currency] ?? 0) + p.value_base_ccy;
    }
    for (const c of snapshot.cash_positions) {
      totals[c.currency] = (totals[c.currency] ?? 0) + c.value_base_ccy;
    }
    const total = Object.values(totals).reduce((s, v) => s + v, 0);
    for (const [currency, value] of Object.entries(totals)) {
      slices.push({ currency, value, pct: total ? (value / total) * 100 : 0 });
    }
    slices.sort((a, b) => b.value - a.value);
  }

  return (
    <div className="space-y-8">
      <div>
        <h1 className="font-display text-2xl mb-1 flex items-center gap-2">
          Currency Exposure
          <InfoTooltip>
            <p className="mb-2">
              This shows the <strong>quotation currency</strong> — the currency each position or
              cash balance is actually held/quoted in — not a true look-through into what a fund
              holds internally.
            </p>
            <p>
              Example: a EUR-listed ETF that invests in US stocks still counts entirely as EUR
              here, because that's the currency it's quoted and traded in, even though its
              underlying holdings are USD-denominated.
            </p>
          </InfoTooltip>
        </h1>
        <p className="text-muted text-sm">
          How much of this portfolio is priced in each currency — based on the currency each
          position and cash balance is actually quoted/held in, not a look-through into what a
          fund holds underneath (a EUR-listed ETF can still hold USD-denominated stocks; that
          detail isn't tracked here).
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
          <p className="text-muted text-sm">No positions or balances yet in this portfolio.</p>
        ) : (
          <div className="flex flex-col md:flex-row items-center gap-6">
            <ResponsiveContainer width="100%" height={320} className="md:max-w-sm">
              <PieChart>
                <Pie
                  data={slices}
                  dataKey="value"
                  nameKey="currency"
                  innerRadius={60}
                  outerRadius={120}
                  paddingAngle={1}
                  stroke={chart.panelBg}
                  strokeWidth={2}
                >
                  {slices.map((s, i) => (
                    <Cell key={s.currency} fill={chart.categorical[i % chart.categorical.length]} />
                  ))}
                </Pie>
                <Tooltip
                  contentStyle={{ background: chart.panelBg, border: `1px solid ${chart.grid}`, borderRadius: 6, fontSize: 12 }}
                  formatter={(v: any, _name: any, item: any) => [
                    formatMoney(Number(v), snapshot.base_currency),
                    item?.payload?.currency,
                  ]}
                />
              </PieChart>
            </ResponsiveContainer>

            <div className="flex-1 w-full">
              <ResponsiveTable
                keyFor={(s) => s.currency}
                rows={slices}
                columns={
                  [
                    {
                      header: "Currency",
                      cell: (s) => {
                        const i = slices.indexOf(s);
                        return (
                          <>
                            <span
                              className="inline-block w-2.5 h-2.5 rounded-full mr-2 align-middle"
                              style={{ backgroundColor: chart.categorical[i % chart.categorical.length] }}
                            />
                            {s.currency}
                          </>
                        );
                      },
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
