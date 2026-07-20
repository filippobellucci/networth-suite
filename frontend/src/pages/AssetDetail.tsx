import { useEffect, useState, useCallback } from "react";
import { useParams, Link } from "react-router-dom";
import { api } from "../api/client";
import type { Asset, AssetPricePoint, GrowthStats } from "../types";
import { ASSET_CLASS_LABELS, ALLOCATION_CATEGORY_LABELS } from "../types";
import { todayISO } from "../lib/format";
import AssetPriceChart from "../components/AssetPriceChart";

export default function AssetDetail() {
  const { id } = useParams<{ id: string }>();
  const assetId = id!;

  const [asset, setAsset] = useState<Asset | null>(null);
  const [points, setPoints] = useState<AssetPricePoint[]>([]);
  const [growth, setGrowth] = useState<GrowthStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(() => {
    setLoading(true);
    api
      .getAsset(assetId)
      .then((a) => {
        setAsset(a);
        return Promise.all([api.getAssetPriceHistory(a), api.getAssetGrowth(assetId)]);
      })
      .then(([pts, g]) => {
        setPoints(pts);
        setGrowth(g);
      })
      .catch((e) => setError(String(e.message || e)))
      .finally(() => setLoading(false));
  }, [assetId]);

  useEffect(reload, [reload]);

  if (loading) return <div className="text-muted">Loading asset…</div>;
  if (error || !asset)
    return (
      <div className="card p-6 border-loss/40">
        <p className="text-loss text-sm">{error || "Asset not found"}</p>
      </div>
    );

  return (
    <div className="space-y-8">
      <div>
        <Link to="/assets" className="text-muted text-xs hover:text-brass">
          ← Asset Catalogue
        </Link>
        <div className="flex items-center gap-3 mt-1 flex-wrap">
          <h1 className="font-display text-2xl">{asset.name}</h1>
          {asset.ticker && <span className="text-muted font-mono text-sm">{asset.ticker}</span>}
          {asset.category && (
            <span className="px-2 py-0.5 rounded-full border ledger-rule text-brass-dim text-xs">
              {ALLOCATION_CATEGORY_LABELS[asset.category]}
            </span>
          )}
        </div>
        <p className="text-muted text-sm mt-1">
          {ASSET_CLASS_LABELS[asset.asset_class]} · {asset.currency}
          {asset.isin && <> · {asset.isin}</>}
        </p>
      </div>

      <div className="card p-8">
        {asset.ticker ? (
          <AssetPriceChart
            points={points}
            currency={asset.currency}
            growth={growth}
            fetchIntraday={() => api.getAssetIntraday(asset.ticker!, todayISO())}
          />
        ) : (
          <AssetPriceChart points={points} currency={asset.currency} growth={growth} />
        )}
      </div>

      {!asset.ticker && (
        <div className="card p-4 text-sm text-muted">
          This asset has no ticker, so its price comes only from the manual prices you've entered
          over time (real estate, private holdings, etc.) — no hourly/live data is available for
          it.
        </div>
      )}
    </div>
  );
}
