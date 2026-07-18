import { useEffect, useState, useCallback } from "react";
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from "recharts";
import { api } from "../api/client";
import type { Asset, AssetAllocationRecord, Portfolio, PortfolioGeoAllocation } from "../types";
import { formatPct, formatDate } from "../lib/format";

export default function GeoAllocation() {
  const [assets, setAssets] = useState<Asset[]>([]);
  const [allocations, setAllocations] = useState<Record<string, AssetAllocationRecord>>({});
  const [portfolios, setPortfolios] = useState<Portfolio[]>([]);
  const [selectedPortfolio, setSelectedPortfolio] = useState<string>("");
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
    api.getPortfolioGeoAllocation(selectedPortfolio).then(setPortfolioAllocation).catch(() => setPortfolioAllocation(null));
  }, [selectedPortfolio, allocations]);

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
        <div className="flex items-center justify-between mb-4">
          <h2 className="font-display text-lg">Exposure by portfolio</h2>
          <select className="input" value={selectedPortfolio} onChange={(e) => setSelectedPortfolio(e.target.value)}>
            {portfolios.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
        </div>

        {!portfolioAllocation ? (
          <p className="text-muted text-sm">Select a portfolio.</p>
        ) : portfolioAllocation.regions.length === 0 ? (
          <p className="text-muted text-sm">
            No allocation data available yet: upload at least one file for the ETFs in this
            portfolio below.
          </p>
        ) : (
          <>
            <p className="text-xs text-muted mb-3">
              Coverage: {formatPct(portfolioAllocation.covered_weight_pct)} of the portfolio's value
            </p>
            <ResponsiveContainer width="100%" height={Math.max(200, portfolioAllocation.regions.length * 28)}>
              <BarChart
                data={portfolioAllocation.regions}
                layout="vertical"
                margin={{ top: 4, right: 24, left: 8, bottom: 4 }}
              >
                <CartesianGrid stroke="#2A3937" strokeDasharray="2 4" horizontal={false} />
                <XAxis
                  type="number"
                  tick={{ fill: "#8CA39C", fontSize: 11, fontFamily: "IBM Plex Mono" }}
                  axisLine={{ stroke: "#2A3937" }}
                  tickLine={false}
                  tickFormatter={(v) => `${v}%`}
                />
                <YAxis
                  type="category"
                  dataKey="country_name"
                  tick={{ fill: "#ECE8D9", fontSize: 12 }}
                  axisLine={false}
                  tickLine={false}
                  width={140}
                />
                <Tooltip
                  contentStyle={{ background: "#1A2624", border: "1px solid #2A3937", borderRadius: 6, fontSize: 12 }}
                  formatter={(v: any) => [`${Number(v).toFixed(2)}%`, "Weight"]}
                />
                <Bar dataKey="weight_pct" fill="#C8A661" radius={[0, 3, 3, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </>
        )}

        {portfolioAllocation && portfolioAllocation.missing_assets.length > 0 && (
          <div className="mt-4 pt-4 border-t ledger-rule">
            <p className="text-xs uppercase tracking-wide text-muted mb-2">
              Assets without an allocation file (excluded from the chart)
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
