import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import type { Asset, PortfolioSnapshot } from "../types";
import InfoTooltip from "./InfoTooltip";
import { ASSET_CLASS_LABELS, ALLOCATION_CATEGORY_LABELS } from "../types";
import { formatMoney, formatMoneyPrecise } from "../lib/format";
import ResponsiveTable, { type ResponsiveColumn } from "./ResponsiveTable";
import AddPositionForm from "./AddPositionForm";
import { errorText } from "../lib/errors";

/**
 * A position is stored as a time series of holding entries, so "remove it
 * from this portfolio" means deleting every entry for that asset. Shared by
 * the Positions table and the per-section position tables in BalanceSection,
 * which offer the exact same action.
 */
export async function removeAssetFromPortfolio(portfolioId: string, assetId: string, assetName: string, onChanged: () => void) {
  if (!confirm(`Remove "${assetName}" from this portfolio? This will delete all history for this position.`)) return;
  try {
    const entries = await api.listHoldings(portfolioId, assetId);
    await Promise.all(entries.map((e) => api.deleteHolding(e.id)));
  } catch (e) {
    // A partial failure matters here: some entries may already be gone, so
    // the caller still reloads below to show whatever actually remains.
    alert(`Could not fully remove "${assetName}": ${errorText(e)}`);
  }
  onChanged();
}

export default function PositionsSection({
  snapshot,
  allAssets,
  portfolioId,
  onChanged,
}: {
  snapshot: PortfolioSnapshot;
  allAssets: Asset[];
  portfolioId: string;
  onChanged: () => void;
}) {
  const [showAdd, setShowAdd] = useState(false);

  return (
    <div>
      <div className="flex items-center justify-between mb-3">
        <h2 className="font-display text-lg">Positions</h2>
        <button className="btn-primary text-sm" onClick={() => setShowAdd((s) => !s)}>
          + Add position
        </button>
      </div>

      {showAdd && (
        <AddPositionForm
          portfolioId={portfolioId}
          allAssets={allAssets}
          onDone={() => {
            setShowAdd(false);
            onChanged();
          }}
        />
      )}

      {snapshot.positions.length === 0 ? (
        <div className="card p-6 text-muted text-sm">No holdings in this portfolio yet.</div>
      ) : (
        <ResponsiveTable
          keyFor={(pos) => pos.asset_id}
          rows={snapshot.positions}
          columns={
            [
              {
                header: "Asset",
                className: "font-sans",
                cell: (pos) => (
                  <Link to={`/assets/${pos.asset_id}`} className="hover:text-brass transition-colors">
                    {pos.asset_name}
                  </Link>
                ),
              },
              { header: "Ticker", className: "text-muted text-xs", cell: (pos) => pos.ticker || "—" },
              {
                header: "Type",
                className: "font-sans text-muted text-xs",
                cell: (pos) => ASSET_CLASS_LABELS[pos.asset_class],
              },
              {
                header: "Tag",
                className: "text-xs font-sans",
                cell: (pos) =>
                  pos.category ? (
                    <span className="px-2 py-0.5 rounded-full border ledger-rule text-brass-dim">
                      {ALLOCATION_CATEGORY_LABELS[pos.category]}
                    </span>
                  ) : (
                    <span className="text-muted">—</span>
                  ),
              },
              {
                header: "Quantity",
                className: "text-right num",
                headClassName: "text-right",
                cell: (pos) => pos.quantity,
              },
              {
                header: "Price",
                className: "text-right num",
                headClassName: "text-right",
                cell: (pos) => (
                  <>
                    {pos.price !== null ? formatMoneyPrecise(pos.price, pos.price_currency) : "—"}
                    {pos.price_source === "historical_fallback" && (
                      <span className="inline-flex items-center gap-1 ml-1">
                        <span className="text-brass-dim text-xs font-sans">≈</span>
                        <InfoTooltip>
                          <p>
                            The real historical price for this date couldn't be fetched (usually a
                            temporary Yahoo Finance issue, or right after restarting the app when
                            its price cache is empty), so today's price is used here as an
                            approximation instead of counting this position as worth nothing.
                          </p>
                        </InfoTooltip>
                      </span>
                    )}
                    {pos.price_source === "unavailable" && (
                      <span className="inline-flex items-center gap-1 ml-1">
                        <span className="text-loss text-xs font-sans">n/a</span>
                        <InfoTooltip>
                          <p className="mb-2">
                            Yahoo Finance (this app's price source) couldn't find a quote for this
                            asset's exact ticker.
                          </p>
                          <p className="mb-2">
                            The most common cause is a missing or wrong <strong>exchange
                            suffix</strong> — non-US listings need one, e.g.{" "}
                            <span className="font-mono">.MI</span> for Milan,{" "}
                            <span className="font-mono">.DE</span> for Xetra/Frankfurt,{" "}
                            <span className="font-mono">.AS</span> for Amsterdam,{" "}
                            <span className="font-mono">.PA</span> for Paris. The same fund is
                            sometimes cross-listed on several exchanges under different suffixes —
                            search the ticker on{" "}
                            <span className="font-mono">finance.yahoo.com</span> to confirm which
                            one Yahoo actually lists it under.
                          </p>
                          <p>
                            If the ticker looks correct, check the price-feed service's own logs
                            (<span className="font-mono">docker compose logs price-feed</span>) for
                            the underlying error — it could be a temporary Yahoo Finance
                            connectivity issue rather than a wrong ticker.
                          </p>
                        </InfoTooltip>
                      </span>
                    )}
                    {pos.price_source === "manual" && (
                      <span className="text-brass-dim text-xs ml-1 font-sans">manual</span>
                    )}
                  </>
                ),
              },
              {
                header: "Value",
                className: "text-right num",
                headClassName: "text-right",
                cell: (pos) => formatMoney(pos.value_base_ccy, snapshot.base_currency),
              },
              {
                header: "",
                noMobileLabel: true,
                className: "text-right font-sans",
                cell: (pos) => (
                  <button
                    className="text-muted hover:text-loss text-xs"
                    onClick={() => removeAssetFromPortfolio(portfolioId, pos.asset_id, pos.asset_name, onChanged)}
                  >
                    Remove
                  </button>
                ),
              },
            ] as ResponsiveColumn<(typeof snapshot.positions)[number]>[]
          }
        />
      )}
    </div>
  );
}
