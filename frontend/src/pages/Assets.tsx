import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import type { Asset, AssetClass, AllocationCategory } from "../types";
import { ASSET_CLASS_LABELS, ALLOCATION_CATEGORY_LABELS } from "../types";
import ResponsiveTable, { type ResponsiveColumn } from "../components/ResponsiveTable";

const ASSET_CLASSES: AssetClass[] = ["ETF", "STOCK", "BOND", "CRYPTO", "CASH", "REAL_ESTATE", "PENSION_FUND", "OTHER"];

export default function Assets() {
  const [assets, setAssets] = useState<Asset[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [editing, setEditing] = useState<Asset | null>(null);
  const [search, setSearch] = useState("");

  function reload(currentSearch = search) {
    setLoading(true);
    api
      .listAssets(currentSearch.trim() || undefined)
      .then(setAssets)
      .catch((e) => setError(String(e.message || e)))
      .finally(() => setLoading(false));
  }

  // Re-queries the backend's own search (name/ticker) rather than filtering
  // the already-fetched page client-side, so it also finds assets not
  // currently loaded. Debounced while typing, but immediate on mount: a
  // separate mount effect alongside this one meant the very first render
  // fired the same request twice, 300ms apart.
  const isFirstLoad = useRef(true);
  useEffect(() => {
    if (isFirstLoad.current) {
      isFirstLoad.current = false;
      reload(search);
      return;
    }
    const timer = setTimeout(() => reload(search), 300);
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [search]);

  async function handleDelete(a: Asset) {
    if (!confirm(`Delete "${a.name}" from the catalogue? It will be removed from every portfolio it appears in.`)) return;
    try {
      await api.deleteAsset(a.id);
      reload();
    } catch (e: any) {
      alert(e.message || e);
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="font-display text-2xl mb-1">Asset Catalogue</h1>
          <p className="text-muted text-sm">Assets shared across all portfolios.</p>
        </div>
        <button
          className="btn-primary"
          onClick={() => {
            setEditing(null);
            setShowForm(true);
          }}
        >
          + New asset
        </button>
      </div>

      <div className="relative max-w-sm">
        <svg
          width="16"
          height="16"
          viewBox="0 0 20 20"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.8"
          className="absolute left-3 top-1/2 -translate-y-1/2 text-muted pointer-events-none"
          aria-hidden="true"
        >
          <circle cx="9" cy="9" r="6" />
          <path d="M17 17 L13.5 13.5" strokeLinecap="round" />
        </svg>
        <input
          className="input w-full pl-9"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search by name or ticker…"
          type="search"
          aria-label="Search assets"
        />
      </div>

      {showForm && (
        <AssetForm
          // Remounts whenever the form switches to a different asset (or to
          // "new"). AssetForm seeds its fields from `initial` with useState,
          // which only runs on mount -- so clicking "Edit" on a second asset
          // while the form was already open left the FIRST asset's values in
          // the inputs while `initial` pointed at the second one, and saving
          // wrote one asset's details over the other. "+ New asset" from an
          // open edit form had the same shape: it created a duplicate of the
          // asset being edited.
          key={editing?.id ?? "new"}
          initial={editing}
          onDone={() => {
            setShowForm(false);
            reload();
          }}
          onCancel={() => setShowForm(false)}
        />
      )}

      {error && <p className="text-loss text-sm">{error}</p>}
      {loading ? (
        <div className="text-muted">Loading…</div>
      ) : assets.length === 0 ? (
        <div className="card p-6 text-muted text-sm">
          {search.trim() ? `No assets match "${search.trim()}".` : "No assets yet."}
        </div>
      ) : (
        <ResponsiveTable
          keyFor={(a) => a.id}
          rows={assets}
          columns={
            [
              {
                header: "Name",
                cell: (a) => (
                  <Link to={`/assets/${a.id}`} className="hover:text-brass transition-colors">
                    {a.name}
                  </Link>
                ),
              },
              { header: "Ticker", cell: (a) => a.ticker || "—", className: "font-mono text-muted" },
              { header: "Type", cell: (a) => ASSET_CLASS_LABELS[a.asset_class], className: "text-muted text-xs" },
              {
                header: "Tag",
                cell: (a) =>
                  a.category ? (
                    <span className="px-2 py-0.5 rounded-full border ledger-rule text-brass-dim">
                      {ALLOCATION_CATEGORY_LABELS[a.category]}
                    </span>
                  ) : (
                    <span className="text-muted">—</span>
                  ),
                className: "text-xs",
              },
              { header: "Currency", cell: (a) => a.currency, className: "font-mono text-muted" },
              {
                header: "",
                noMobileLabel: true,
                className: "text-right",
                cell: (a) => (
                  <>
                    <button
                      className="text-brass text-xs"
                      onClick={() => {
                        setEditing(a);
                        setShowForm(true);
                      }}
                    >
                      Edit
                    </button>
                    <button className="text-muted text-xs hover:text-loss ml-3" onClick={() => handleDelete(a)}>
                      Delete
                    </button>
                  </>
                ),
              },
            ] as ResponsiveColumn<Asset>[]
          }
        />
      )}
    </div>
  );
}

function AssetForm({
  initial,
  onDone,
  onCancel,
}: {
  initial: Asset | null;
  onDone: () => void;
  onCancel: () => void;
}) {
  const [name, setName] = useState(initial?.name ?? "");
  const [ticker, setTicker] = useState(initial?.ticker ?? "");
  const [isin, setIsin] = useState(initial?.isin ?? "");
  const [assetClass, setAssetClass] = useState<AssetClass>(initial?.asset_class ?? "ETF");
  const [category, setCategory] = useState<AllocationCategory | "">(initial?.category ?? "");
  const [currency, setCurrency] = useState(initial?.currency ?? "EUR");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError(null);
    try {
      // null, not undefined, for the fields that can be emptied: JSON.stringify
      // drops an undefined value entirely, and the backend leaves out whatever
      // a PATCH doesn't mention. So clearing the ticker sent a body with no
      // `ticker` key at all and the old one stayed — an asset saved with the
      // wrong ticker could not be corrected by emptying the field, only by
      // deleting the asset, which takes every holding of it with it. null says
      // "set this to nothing", which is what the column allows and what the
      // empty field means. Both columns are nullable, so this is equally
      // correct when creating.
      const payload = {
        name: name.trim(),
        ticker: ticker.trim() || null,
        isin: isin.trim() || null,
        asset_class: assetClass,
        category: category || null,
        currency,
      };
      if (initial) {
        await api.updateAsset(initial.id, payload as any);
      } else {
        await api.createAsset(payload as any);
      }
      onDone();
    } catch (e: any) {
      setError(String(e.message || e));
    } finally {
      setSaving(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="card p-5 space-y-4">
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="text-xs uppercase tracking-wide text-muted block mb-1">Name</label>
          <input className="input w-full" value={name} onChange={(e) => setName(e.target.value)} autoFocus />
        </div>
        <div>
          <label className="text-xs uppercase tracking-wide text-muted block mb-1">Ticker (yfinance)</label>
          <input className="input w-full" value={ticker} onChange={(e) => setTicker(e.target.value)} placeholder="e.g. SWDA.MI" />
        </div>
        <div>
          <label className="text-xs uppercase tracking-wide text-muted block mb-1">ISIN</label>
          <input className="input w-full" value={isin} onChange={(e) => setIsin(e.target.value)} />
        </div>
        <div>
          <label className="text-xs uppercase tracking-wide text-muted block mb-1">Type</label>
          <select className="input w-full" value={assetClass} onChange={(e) => setAssetClass(e.target.value as AssetClass)}>
            {ASSET_CLASSES.map((c) => (
              <option key={c} value={c}>
                {ASSET_CLASS_LABELS[c]}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className="text-xs uppercase tracking-wide text-muted block mb-1">
            Tag <span className="normal-case">(for the Allocation view's Category and Geography tabs)</span>
          </label>
          <select
            className="input w-full"
            value={category}
            onChange={(e) => setCategory(e.target.value as AllocationCategory | "")}
          >
            <option value="">None</option>
            <option value="STOCK">Stock</option>
            <option value="BOND">Bond</option>
            <option value="EMERGENCY_FUND">Emergency Fund</option>
          </select>
        </div>
        <div>
          <label className="text-xs uppercase tracking-wide text-muted block mb-1">Currency</label>
          <select className="input w-full" value={currency} onChange={(e) => setCurrency(e.target.value)}>
            <option>EUR</option>
            <option>USD</option>
            <option>GBP</option>
            <option>CHF</option>
          </select>
        </div>
      </div>
      {error && <p className="text-loss text-sm">{error}</p>}
      <div className="flex gap-3">
        <button className="btn-primary" disabled={saving}>
          {saving ? "Saving…" : initial ? "Save changes" : "Create asset"}
        </button>
        <button type="button" className="btn-ghost" onClick={onCancel}>
          Cancel
        </button>
      </div>
    </form>
  );
}
