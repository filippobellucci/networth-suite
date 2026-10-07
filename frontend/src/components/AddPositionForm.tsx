import { useState } from "react";
import { api } from "../api/client";
import type { Asset, AssetClass, AllocationCategory } from "../types";
import { ASSET_CLASS_LABELS } from "../types";
import { todayISO, parseLocaleFloat } from "../lib/format";
import { errorText } from "../lib/errors";

const ASSET_CLASSES: AssetClass[] = ["ETF", "STOCK", "BOND", "CRYPTO", "REAL_ESTATE", "PENSION_FUND", "OTHER"];

export default function AddPositionForm({
  portfolioId,
  allAssets,
  onDone,
  defaultCategory,
}: {
  portfolioId: string;
  allAssets: Asset[];
  onDone: () => void;
  /**
   * Preselects the tag when creating a brand-new asset from this form --
   * pure convenience for opening this form from a filtered section (e.g.
   * Emergency Fund). Never forced: it's just the select's starting value,
   * still fully editable, and only applies to "+ New asset" mode -- picking
   * an "Existing asset" always keeps whatever tag that asset already has in
   * the catalogue (changing it here would silently retag it everywhere else
   * it's held, which this form deliberately never does).
   */
  defaultCategory?: AllocationCategory;
}) {
  const [mode, setMode] = useState<"existing" | "new">(allAssets.length ? "existing" : "new");
  const [assetId, setAssetId] = useState(allAssets[0]?.id ?? "");
  const [quantity, setQuantity] = useState("");
  const [manualPrice, setManualPrice] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // new asset fields
  const [newName, setNewName] = useState("");
  const [newTicker, setNewTicker] = useState("");
  const [newClass, setNewClass] = useState<AssetClass>("ETF");
  const [newCategory, setNewCategory] = useState<AllocationCategory | "">(defaultCategory ?? "");
  const [newCurrency, setNewCurrency] = useState("EUR");

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError(null);
    try {
      let finalAssetId = assetId;
      if (mode === "new") {
        if (!newName.trim()) throw new Error("Asset name is required");
        const created = await api.createAsset({
          name: newName.trim(),
          ticker: newTicker.trim() || undefined,
          asset_class: newClass,
          category: newCategory || null,
          currency: newCurrency,
        } as any);
        finalAssetId = created.id;
      }
      if (!finalAssetId) throw new Error("Select an asset");
      const qty = parseLocaleFloat(quantity);
      if (isNaN(qty)) throw new Error("Invalid quantity");

      // Checked like the quantity above: JSON.stringify writes NaN as null,
      // which would create the position with no manual price at all.
      let price: number | null = null;
      if (manualPrice.trim()) {
        price = parseLocaleFloat(manualPrice);
        if (isNaN(price)) throw new Error("Invalid manual price");
      }

      await api.addHolding(portfolioId, {
        asset_id: finalAssetId,
        entry_date: todayISO(),
        quantity: qty,
        manual_price: price,
      });
      onDone();
    } catch (e) {
      setError(errorText(e));
    } finally {
      setSaving(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="card p-5 mb-4 space-y-4">
      <div className="flex gap-4 text-sm">
        <button
          type="button"
          className={mode === "existing" ? "text-brass" : "text-muted"}
          onClick={() => setMode("existing")}
        >
          Existing asset
        </button>
        <button type="button" className={mode === "new" ? "text-brass" : "text-muted"} onClick={() => setMode("new")}>
          + New asset
        </button>
      </div>

      {mode === "existing" ? (
        <select className="input w-full" value={assetId} onChange={(e) => setAssetId(e.target.value)}>
          {allAssets.map((a) => (
            <option key={a.id} value={a.id}>
              {a.name} {a.ticker ? `(${a.ticker})` : ""}
            </option>
          ))}
        </select>
      ) : (
        <div className="grid grid-cols-2 gap-3">
          <input className="input" placeholder="Name (e.g. iShares Core MSCI World)" value={newName} onChange={(e) => setNewName(e.target.value)} />
          <input className="input" placeholder="Ticker (optional, e.g. SWDA.MI)" value={newTicker} onChange={(e) => setNewTicker(e.target.value)} />
          <select className="input" value={newClass} onChange={(e) => setNewClass(e.target.value as AssetClass)}>
            {ASSET_CLASSES.map((c) => (
              <option key={c} value={c}>
                {ASSET_CLASS_LABELS[c]}
              </option>
            ))}
          </select>
          <select
            className="input"
            value={newCategory}
            onChange={(e) => setNewCategory(e.target.value as AllocationCategory | "")}
          >
            <option value="">No tag</option>
            <option value="STOCK">Stock</option>
            <option value="BOND">Bond</option>
            <option value="EMERGENCY_FUND">Emergency Fund</option>
          </select>
          <select className="input" value={newCurrency} onChange={(e) => setNewCurrency(e.target.value)}>
            <option>EUR</option>
            <option>USD</option>
            <option>GBP</option>
            <option>CHF</option>
          </select>
        </div>
      )}

      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="field-label">Quantity</label>
          <input className="input w-full" value={quantity} onChange={(e) => setQuantity(e.target.value)} placeholder="e.g. 12.5" inputMode="decimal" />
        </div>
        <div>
          <label className="field-label">
            Manual price <span className="normal-case">(leave empty to use the live price via ticker)</span>
          </label>
          <input className="input w-full" value={manualPrice} onChange={(e) => setManualPrice(e.target.value)} placeholder="e.g. 250000" inputMode="decimal" />
        </div>
      </div>

      {error && <p className="text-loss text-sm">{error}</p>}

      <div className="flex gap-3">
        <button className="btn-primary" disabled={saving}>
          {saving ? "Saving…" : "Add"}
        </button>
        <button type="button" className="btn-ghost" onClick={onDone}>
          Cancel
        </button>
      </div>
    </form>
  );
}
