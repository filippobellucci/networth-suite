import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { Asset, AssetClass, InstrumentType } from "../types";
import { ASSET_CLASS_LABELS, INSTRUMENT_TYPE_LABELS } from "../types";

const ASSET_CLASSES: AssetClass[] = ["ETF", "STOCK", "BOND", "CRYPTO", "CASH", "REAL_ESTATE", "PENSION_FUND", "OTHER"];

export default function Assets() {
  const [assets, setAssets] = useState<Asset[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [editing, setEditing] = useState<Asset | null>(null);

  function reload() {
    setLoading(true);
    api.listAssets().then(setAssets).catch((e) => setError(String(e.message || e))).finally(() => setLoading(false));
  }
  useEffect(reload, []);

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
      <div className="flex items-center justify-between">
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

      {showForm && (
        <AssetForm
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
        <div className="card p-6 text-muted text-sm">No assets yet.</div>
      ) : (
        <div className="card overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs uppercase tracking-wide text-muted border-b ledger-rule">
                <th className="px-5 py-3 font-normal">Name</th>
                <th className="px-5 py-3 font-normal">Ticker</th>
                <th className="px-5 py-3 font-normal">Type</th>
                <th className="px-5 py-3 font-normal">Tag</th>
                <th className="px-5 py-3 font-normal">Currency</th>
                <th className="px-5 py-3 font-normal"></th>
              </tr>
            </thead>
            <tbody>
              {assets.map((a) => (
                <tr key={a.id} className="border-b ledger-rule last:border-0">
                  <td className="px-5 py-3">{a.name}</td>
                  <td className="px-5 py-3 font-mono text-muted">{a.ticker || "—"}</td>
                  <td className="px-5 py-3 text-muted text-xs">{ASSET_CLASS_LABELS[a.asset_class]}</td>
                  <td className="px-5 py-3 text-xs">
                    {a.instrument_type ? (
                      <span className="px-2 py-0.5 rounded-full border ledger-rule text-brass-dim">
                        {INSTRUMENT_TYPE_LABELS[a.instrument_type]}
                      </span>
                    ) : (
                      <span className="text-muted">—</span>
                    )}
                  </td>
                  <td className="px-5 py-3 font-mono text-muted">{a.currency}</td>
                  <td className="px-5 py-3 text-right space-x-3">
                    <button
                      className="text-brass text-xs"
                      onClick={() => {
                        setEditing(a);
                        setShowForm(true);
                      }}
                    >
                      Edit
                    </button>
                    <button className="text-muted text-xs hover:text-loss" onClick={() => handleDelete(a)}>
                      Delete
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
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
  const [instrumentType, setInstrumentType] = useState<InstrumentType | "">(initial?.instrument_type ?? "");
  const [currency, setCurrency] = useState(initial?.currency ?? "EUR");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError(null);
    try {
      const payload = {
        name: name.trim(),
        ticker: ticker.trim() || undefined,
        isin: isin.trim() || undefined,
        asset_class: assetClass,
        instrument_type: instrumentType || null,
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
            Tag <span className="normal-case">(for geographic allocation views)</span>
          </label>
          <select
            className="input w-full"
            value={instrumentType}
            onChange={(e) => setInstrumentType(e.target.value as InstrumentType | "")}
          >
            <option value="">None</option>
            <option value="STOCK">Stock</option>
            <option value="BOND">Bond</option>
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
