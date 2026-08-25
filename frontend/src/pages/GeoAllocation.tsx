import { useEffect, useState, useCallback, lazy, Suspense } from "react";
import { PieChart, Pie, Cell, Tooltip, ResponsiveContainer } from "recharts";
import { api } from "../api/client";
import type { Asset, AssetAllocationRecord, Portfolio, PortfolioGeoAllocation } from "../types";
import { formatPct, formatDate } from "../lib/format";
import { ALLOCATION_CATEGORY_LABELS } from "../types";
import { useTheme } from "../context/ThemeContext";
import { getChartTheme } from "../lib/chartTheme";
import InfoTooltip from "../components/InfoTooltip";
import ResponsiveTable, { type ResponsiveColumn } from "../components/ResponsiveTable";
import SegmentedControl from "../components/SegmentedControl";
import { useIsMobile } from "../context/ViewModeContext";

// Lazy-loaded: pulls in d3-geo, topojson-client, and ~100KB of world map
// data, none of which should sit in the main bundle for people who never
// open this tab (or never switch to the Map view within it).
const WorldMapChart = lazy(() => import("../components/WorldMapChart"));

export default function GeoAllocation() {
  const { theme } = useTheme();
  const chart = getChartTheme(theme === "dark");
  const isMobile = useIsMobile();
  const SLICE_COLORS = chart.categorical;
  const [assets, setAssets] = useState<Asset[]>([]);
  const [allocations, setAllocations] = useState<Record<string, AssetAllocationRecord>>({});
  const [portfolios, setPortfolios] = useState<Portfolio[]>([]);
  const [selectedPortfolio, setSelectedPortfolio] = useState<string>("");
  const [typeFilter, setTypeFilter] = useState<"" | "STOCK" | "BOND">("");
  const [groupBy, setGroupBy] = useState<"country" | "region">("country");
  const [viewMode, setViewMode] = useState<"chart" | "map">("chart");
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
          <div className={isMobile ? "flex flex-col items-stretch gap-3 w-full" : "flex items-center gap-3"}>
            {groupBy === "country" && (
              <div className="flex items-center gap-1.5">
                <SegmentedControl
                  options={[
                    { value: "chart", label: "Chart" },
                    { value: "map", label: "Map" },
                  ]}
                  value={viewMode}
                  onChange={setViewMode}
                  className={isMobile ? "flex-1" : undefined}
                />
                {viewMode === "map" && (
                  <InfoTooltip>
                    <p>
                      Each country's shade is <strong>relative to your largest single-country
                      exposure</strong>, not an absolute scale — so if one country dominates the
                      portfolio, smaller allocations still show up clearly instead of washing out
                      next to it.
                    </p>
                  </InfoTooltip>
                )}
              </div>
            )}
            <SegmentedControl
              options={[
                { value: "country", label: "By country" },
                { value: "region", label: "By region" },
              ]}
              value={groupBy}
              onChange={setGroupBy}
              className={isMobile ? "w-full" : undefined}
            />
            <div className="flex items-center gap-1.5">
              <SegmentedControl
                options={[
                  { value: "ALL", label: "All" },
                  { value: "STOCK", label: "Stocks" },
                  { value: "BOND", label: "Bonds" },
                ]}
                value={typeFilter || "ALL"}
                onChange={(v) => setTypeFilter(v === "ALL" ? "" : v)}
                className={isMobile ? "flex-1" : undefined}
              />
              <InfoTooltip>
                <p>
                  Filters which assets count toward the chart/table below, based on each asset's
                  Stock/Bond tag (set in Portfolio Allocation). <strong>All</strong> includes both;
                  assets with no Stock/Bond tag, and cash-like balances, are never included here
                  since only ETF factsheet uploads have a country breakdown to show.
                </p>
              </InfoTooltip>
            </div>
            <select
              className={`input ${isMobile ? "w-full" : ""}`}
              value={selectedPortfolio}
              onChange={(e) => setSelectedPortfolio(e.target.value)}
            >
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

            <div className="flex justify-center">
              {viewMode === "map" && groupBy === "country" ? (
                <div className="w-full max-w-3xl">
                  <Suspense fallback={<p className="text-muted text-sm text-center py-12">Loading map…</p>}>
                    <WorldMapChart regions={portfolioAllocation.regions} />
                  </Suspense>
                </div>
              ) : (
                <ResponsiveContainer width="100%" height={320} className="max-w-sm">
                  <PieChart>
                    <Pie
                      data={portfolioAllocation.regions}
                      dataKey="weight_pct"
                      nameKey="country_name"
                      innerRadius={70}
                      outerRadius={130}
                      paddingAngle={1}
                      stroke={chart.panelBg}
                      strokeWidth={2}
                    >
                      {portfolioAllocation.regions.map((_, i) => (
                        <Cell key={i} fill={SLICE_COLORS[i % SLICE_COLORS.length]} />
                      ))}
                    </Pie>
                    <Tooltip
                      contentStyle={{ background: chart.panelBg, border: `1px solid ${chart.grid}`, borderRadius: 6, fontSize: 12 }}
                      formatter={(v: any, _name: any, item: any) => [`${Number(v).toFixed(2)}%`, item?.payload?.country_name]}
                    />
                  </PieChart>
                </ResponsiveContainer>
              )}
            </div>

            {portfolioAllocation.missing_assets.length > 0 && (
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
          </>
        )}
      </div>

      {portfolioAllocation && portfolioAllocation.regions.length > 0 && (
        <ResponsiveTable
          keyFor={(r) => r.country}
          rows={portfolioAllocation.regions}
          columns={
            [
              {
                header: "Country",
                cell: (r) => {
                  const i = portfolioAllocation!.regions.indexOf(r);
                  return (
                    <>
                      <span
                        className="inline-block w-2.5 h-2.5 rounded-full mr-2 align-middle"
                        style={{ backgroundColor: SLICE_COLORS[i % SLICE_COLORS.length] }}
                      />
                      {r.country_name}
                    </>
                  );
                },
              },
              {
                header: "Weight",
                className: "text-right font-mono num",
                headClassName: "text-right",
                cell: (r) => `${r.weight_pct.toFixed(2)}%`,
              },
            ] as ResponsiveColumn<(typeof portfolioAllocation)["regions"][number]>[]
          }
        />
      )}

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
