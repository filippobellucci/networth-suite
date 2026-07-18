import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import type { Portfolio } from "../types";

export default function Portfolios() {
  const [portfolios, setPortfolios] = useState<Portfolio[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [name, setName] = useState("");
  const [currency, setCurrency] = useState("EUR");
  const [saving, setSaving] = useState(false);

  function reload() {
    setLoading(true);
    api
      .listPortfolios()
      .then(setPortfolios)
      .catch((e) => setError(String(e.message || e)))
      .finally(() => setLoading(false));
  }

  useEffect(reload, []);

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    if (!name.trim()) return;
    setSaving(true);
    try {
      await api.createPortfolio({ name: name.trim(), base_currency: currency });
      setName("");
      setShowForm(false);
      reload();
    } catch (e: any) {
      setError(String(e.message || e));
    } finally {
      setSaving(false);
    }
  }

  async function handleArchive(p: Portfolio) {
    if (!confirm(`Archive "${p.name}"? It will no longer appear in the summary, but the data is kept.`)) return;
    await api.updatePortfolio(p.id, { archived: true });
    reload();
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="font-display text-2xl mb-1">Portfolios</h1>
          <p className="text-muted text-sm">Each portfolio has its own holdings, cash, and history.</p>
        </div>
        <button className="btn-primary" onClick={() => setShowForm((s) => !s)}>
          + New portfolio
        </button>
      </div>

      {showForm && (
        <form onSubmit={handleCreate} className="card p-5 flex items-end gap-4">
          <div className="flex-1">
            <label className="text-xs uppercase tracking-wide text-muted block mb-1">Name</label>
            <input
              className="input w-full"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. Personal, Trading, Pension"
              autoFocus
            />
          </div>
          <div>
            <label className="text-xs uppercase tracking-wide text-muted block mb-1">Base currency</label>
            <select className="input" value={currency} onChange={(e) => setCurrency(e.target.value)}>
              <option>EUR</option>
              <option>USD</option>
              <option>GBP</option>
              <option>CHF</option>
            </select>
          </div>
          <button className="btn-primary" disabled={saving}>
            {saving ? "Saving…" : "Create"}
          </button>
        </form>
      )}

      {error && <div className="text-loss text-sm">{error}</div>}
      {loading ? (
        <div className="text-muted">Loading…</div>
      ) : portfolios.length === 0 ? (
        <div className="card p-6 text-muted text-sm">No portfolios yet.</div>
      ) : (
        <div className="card divide-y ledger-rule">
          {portfolios.map((p) => (
            <div key={p.id} className="flex items-center justify-between px-5 py-4">
              <div>
                <Link to={`/portfolios/${p.id}`} className="font-medium hover:text-brass transition-colors">
                  {p.name}
                </Link>
                <p className="text-xs text-muted mt-0.5">
                  Base currency {p.base_currency} · created on{" "}
                  {new Date(p.created_at).toLocaleDateString("en-US")}
                </p>
              </div>
              <div className="flex items-center gap-3">
                <Link to={`/portfolios/${p.id}`} className="btn-ghost text-sm">
                  Open
                </Link>
                <button className="text-muted text-sm hover:text-loss" onClick={() => handleArchive(p)}>
                  Archive
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
