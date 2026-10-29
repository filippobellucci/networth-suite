import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import type { Portfolio } from "../types";
import { errorText } from "../lib/errors";
import { usePortfolio } from "../context/PortfolioContext";

/**
 * Every portfolio, active and archived -- the one page that lists them all,
 * to create, open, archive and restore them. An archived portfolio keeps all
 * its data; it only leaves the portfolio picker until it is restored.
 */
export default function Portfolios() {
  const { reload: reloadPicker, selectPortfolio } = usePortfolio();
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
      .listPortfolios(true)
      .then(setPortfolios)
      .catch((e) => setError(errorText(e)))
      .finally(() => setLoading(false));
  }

  useEffect(reload, []);

  /** Runs a change, then refreshes both this list and the picker's. */
  async function change(action: () => Promise<unknown>) {
    setError(null);
    try {
      await action();
    } catch (e) {
      setError(errorText(e));
      return;
    }
    reload();
    await reloadPicker();
  }

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    if (!name.trim()) return;
    setSaving(true);
    await change(async () => {
      const created = await api.createPortfolio({ name: name.trim(), base_currency: currency });
      setName("");
      setShowForm(false);
      selectPortfolio(created.id);
    });
    setSaving(false);
  }

  function handleArchive(p: Portfolio) {
    if (!confirm(`Archive "${p.name}"? It leaves the portfolio picker, but all its data is kept and it can be restored from this page.`))
      return;
    change(() => api.updatePortfolio(p.id, { archived: true }));
  }

  function handleRestore(p: Portfolio) {
    change(() => api.updatePortfolio(p.id, { archived: false }));
  }

  const active = portfolios.filter((p) => !p.archived);
  const archived = portfolios.filter((p) => p.archived);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="font-display text-2xl mb-1">Portfolios</h1>
          <p className="text-muted text-sm">
            Each portfolio is kept apart: its own holdings, cash, expenses, budgets and history. The
            picker at the top chooses the one every page shows.
          </p>
        </div>
        <button className="btn-primary" onClick={() => setShowForm((s) => !s)}>
          + New portfolio
        </button>
      </div>

      {showForm && (
        <form onSubmit={handleCreate} className="card p-5 flex items-end gap-4">
          <div className="flex-1">
            <label className="field-label">Name</label>
            <input
              className="input w-full"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. Personal, Trading, Pension"
              autoFocus
            />
          </div>
          <div>
            <label className="field-label">Base currency</label>
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
      ) : active.length === 0 ? (
        <div className="card p-6 text-muted text-sm">
          {archived.length ? "No active portfolios — restore one below, or create a new one." : "No portfolios yet."}
        </div>
      ) : (
        <div className="card divide-y ledger-rule">
          {active.map((p) => (
            <div key={p.id} className="flex items-center justify-between flex-wrap gap-3 px-5 py-4">
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

      {archived.length > 0 && (
        <section aria-label="Archived portfolios">
          <h2 className="font-display text-lg mb-1">Archived</h2>
          <p className="text-muted text-sm mb-3">Kept with all their data; restore one to see it again.</p>
          <div className="card divide-y ledger-rule">
            {archived.map((p) => (
              <div key={p.id} className="flex items-center justify-between flex-wrap gap-3 px-5 py-4">
                <div>
                  <span className="font-medium text-muted">{p.name}</span>
                  <p className="text-xs text-muted mt-0.5">
                    Base currency {p.base_currency} · created on {new Date(p.created_at).toLocaleDateString("en-US")}
                  </p>
                </div>
                <button className="btn-ghost text-sm" onClick={() => handleRestore(p)}>
                  Restore
                </button>
              </div>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
