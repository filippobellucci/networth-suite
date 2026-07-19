import { useEffect, useState, useCallback } from "react";
import { PieChart, Pie, Cell, Tooltip, ResponsiveContainer } from "recharts";
import { api } from "../api/client";
import type { Asset, AssetAllocationRecord, Portfolio, PortfolioGeoAllocation } from "../types";
import { formatPct, formatDate } from "../lib/format";
import { ALLOCATION_CATEGORY_LABELS } from "../types";

// Ledger-themed palette, cycled across slices -- brass first (most prominent
// exposure typically stands out), then a mix of muted sage/clay/teal tones.
const SLICE_COLORS = [
  "#6B4E14", "#2F6B4A", "#9C4A2E", "#3E5F73", "#6B4E82",
  "#6B6355", "#A8862E", "#3D7A6B", "#8A5A2E", "#4A6B8A",
  "#7A4A32", "#2E6B6B", "#8A5A6B", "#6B7A3D", "#6B5A7A",
];

export default function GeoAllocation() {
  const [assets, setAssets] = useState<Asset[]>([]);
  const [allocations, setAllocations] = useState<Record<string, AssetAllocationRecord>>({});
  const [portfolios, setPortfolios] = useState<Portfolio[]>([]);
  const [selectedPortfolio, setSelectedPortfolio] = useState<string>("");
  const [typeFilter, setTypeFilter] = useState<"" | "STOCK" | "BOND">("");
  const [groupBy, setGroupBy] = useState<"country" | "region">("country");
  const [portfolioAllocation, setPortfolioAllocation] = useState<PortfolioGeoAllocation | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(() => {
    setLoading(true);
    Promise.all([api.listAssets(), api.listAssetAllocations(), api.listPortfolios()])
      .then(([assetList, allocList, portfolioList]) => {
        setAssets(assetList);
        const map: Record<string, AssetAllocationRecord> = {};
        allocList.forEach((r) => (map[r.asset_id] = r));
        setAllocations(map);
        setPortfolios(portfolioList);
        if (!selectedPortfolio && portfolioList.length > 0) {
          setSelectedPortfolio(portfolioList[0].id);
        }
      })
      .catch((e) => setError(String(e.message || e)))
      .finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(reload, [reload]);

  useEffect(() => {
    if (!selectedPortfolio) return;
    api
      .getPortfolioGeoAllocation(selectedPortfolio, typeFilter || undefined, groupBy)
      .then(setPortfolioAllocation)
      .catch(() => setPortfolioAllocation(null));
  }, [selectedPortfolio, typeFilter, groupBy, allocations]);

  return (
    <div className="space-y-8">
      <div>
        <h1 className="font-display text-2xl mb-1">Geographic Allocation</h1>
        <p className="text-muted text-sm">
          Upload each ETF's Excel factsheet to extract its country breakdown, then view the combined
          geographic exposure of an entire portfolio.
        </p>
      </div>

      <div className="card p-6">
        <div className="flex items-center justify-between mb-4 flex-wrap gap-3">
          <h2 className="font-display text-lg">Exposure by portfolio</h2>
          <div className="flex items-center gap-3">
            <div className="flex rounded border ledger-rule overflow-hidden text-xs">
              {(["country", "region"] as const).map((g) => (
                <button
                  key={g}
                  onClick={() => setGroupBy(g)}
                  className={`px-3 py-1.5 transition-colors ${
                    groupBy === g ? "bg-brass text-ink font-medium" : "text-muted hover:bg-ink-raised"
                  }`}
                >
                  {g === "country" ? "By country" : "By region"}
                </button>
              ))}
            </div>
            <div className="flex rounded border ledger-rule overflow-hidden text-xs">
              {(["", "STOCK", "BOND"] as const).map((t) => (
                <button
                  key={t || "ALL"}
                  onClick={() => setTypeFilter(t)}
                  className={`px-3 py-1.5 transition-colors ${
                    typeFilter === t ? "bg-brass text-ink font-medium" : "text-muted hover:bg-ink-raised"
                  }`}
                >
                  {t === "" ? "All" : t === "STOCK" ? "Stocks" : "Bonds"}
                </button>
              ))}
            </div>
            <select className="input" value={selectedPortfolio} onChange={(e) => setSelectedPortfolio(e.target.value)}>
              {portfolios.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
          </div>
        </div>

        {!portfolioAllocation ? (
          <p className="text-muted text-sm">Select a portfolio.</p>
        ) : portfolioAllocation.regions.length === 0 ? (
          <div className="text-muted text-sm space-y-2">
            <p>
              No allocation data available{typeFilter ? ` for ${typeFilter === "STOCK" ? "stock" : "bond"}-tagged assets` : ""} in
              this portfolio. This can happen if:
            </p>
            <ul className="list-disc list-inside space-y-1">
              <li>
                no {typeFilter ? (typeFilter === "STOCK" ? "stock-tagged" : "bond-tagged") : ""} ETF in this portfolio
                has an allocation file uploaded yet (see the table below), or
              </li>
              <li>
                the ETFs' current value couldn't be computed because live prices are unavailable —
                check the portfolio page for a price warning, and try "Refresh prices" there.
              </li>
            </ul>
          </div>
        ) : (
          <>
            <p className="text-xs text-muted mb-3">
              Coverage: {formatPct(portfolioAllocation.covered_weight_pct)} of the portfolio's value
            </p>
            <div className="flex flex-col md:flex-row items-center gap-6">
              <ResponsiveContainer width="100%" height={320} className="md:max-w-sm">
                <PieChart>
                  <Pie
                    data={portfolioAllocation.regions}
                    dataKey="weight_pct"
                    nameKey="country_name"
                    innerRadius={60}
                    outerRadius={120}
                    paddingAngle={1}
                    stroke="#DCCDAE"
                    strokeWidth={2}
                  >
                    {portfolioAllocation.regions.map((_, i) => (
                      <Cell key={i} fill={SLICE_COLORS[i % SLICE_COLORS.length]} />
                    ))}
                  </Pie>
                  <Tooltip
                    contentStyle={{ background: "#DCCDAE", border: "1px solid #C7B78D", borderRadius: 6, fontSize: 12 }}
                    formatter={(v: any, _name: any, item: any) => [`${Number(v).toFixed(2)}%`, item?.payload?.country_name]}
                  />
                </PieChart>
              </ResponsiveContainer>

              <div className="flex-1 w-full">
                <table className="w-full text-sm">
                  <tbody>
                    {portfolioAllocation.regions.map((r, i) => (
                      <tr key={r.country} className="border-b ledger-rule last:border-0">
                        <td className="py-2 pr-3">
                          <span
                            className="inline-block w-2.5 h-2.5 rounded-full mr-2 align-middle"
                            style={{ backgroundColor: SLICE_COLORS[i % SLICE_COLORS.length] }}
                          />
                          {r.country_name}
                        </td>
                        <td className="py-2 text-right font-mono num">{r.weight_pct.toFixed(2)}%</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </>
        )}

        {portfolioAllocation && portfolioAllocation.missing_assets.length > 0 && (
          <div className="mt-4 pt-4 border-t ledger-rule">
            <p className="text-xs uppercase tracking-wide text-muted mb-2">
              Assets excluded from the chart above (no allocation file, or no current value available)
            </p>
            <div className="flex flex-wrap gap-2">
              {portfolioAllocation.missing_assets.map((m) => (
                <span key={m.asset_id} className="text-xs bg-ink-raised px-2 py-1 rounded border ledger-rule">
                  {m.asset_name}
                </span>
              ))}
            </div>
          </div>
        )}
      </div>

      <div>
        <h2 className="font-display text-lg mb-3">Allocation files per asset</h2>
        {error && <p className="text-loss text-sm mb-2">{error}</p>}
        {loading ? (
          <div className="text-muted">Loading…</div>
        ) : assets.length === 0 ? (
          <div className="card p-6 text-muted text-sm">
            No assets in the catalogue yet. Add one from the "Asset Catalogue" page.
          </div>
        ) : (
          <div className="card divide-y ledger-rule">
            {assets.map((a) => (
              <AssetAllocationRow key={a.id} asset={a} record={allocations[a.id]} onChanged={reload} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function AssetAllocationRow({
  asset,
  record,
  onChanged,
}: {
  asset: Asset;
  record?: AssetAllocationRecord;
  onChanged: () => void;
}) {
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleFile(file: File | null) {
    if (!file) return;
    setUploading(true);
    setError(null);
    try {
      await api.uploadAssetAllocation(asset.id, file);
      onChanged();
    } catch (e: any) {
      setError(String(e.message || e));
    } finally {
      setUploading(false);
    }
  }

  async function handleDelete() {
    if (!confirm(`Remove the allocation file for "${asset.name}"?`)) return;
    await api.deleteAssetAllocation(asset.id);
    onChanged();
  }

  const topCountries = record
    ? Object.entries(record.result.weights)
        .sort((a, b) => b[1] - a[1])
        .slice(0, 3)
        .map(([code, w]) => `${code} ${(w * 100).toFixed(0)}%`)
        .join(" · ")
    : null;

  return (
    <div className="px-5 py-4 flex items-center justify-between gap-4">
      <div className="min-w-0">
        <p className="font-medium truncate">
          {asset.name} {asset.ticker && <span className="text-muted text-xs">{asset.ticker}</span>}
          {asset.category && (
            <span className="ml-2 px-2 py-0.5 rounded-full border ledger-rule text-brass-dim text-xs">
              {ALLOCATION_CATEGORY_LABELS[asset.category]}
            </span>
          )}
        </p>
        {record ? (
          <p className="text-xs text-muted mt-0.5 truncate">
            {record.original_filename} · uploaded on {formatDate(record.uploaded_at)} · {topCountries}
          </p>
        ) : (
          <p className="text-xs text-muted mt-0.5">No file uploaded</p>
        )}
        {error && <p className="text-xs text-loss mt-1">{error}</p>}
      </div>
      <div className="flex items-center gap-3 shrink-0">
        <label className="btn-ghost text-xs cursor-pointer">
          {uploading ? "Uploading…" : record ? "Replace file" : "Upload file"}
          <input
            type="file"
            accept=".xlsx,.xls"
            className="hidden"
            disabled={uploading}
            onChange={(e) => handleFile(e.target.files?.[0] ?? null)}
          />
        </label>
        {record && (
          <button className="text-muted text-xs hover:text-loss" onClick={handleDelete}>
            Remove
          </button>
        )}
      </div>
    </div>
  );
}
