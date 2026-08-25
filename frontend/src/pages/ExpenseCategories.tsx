import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { ExpenseCategory } from "../types";
import ResponsiveTable, { type ResponsiveColumn } from "../components/ResponsiveTable";

export default function ExpenseCategories() {
  const [categories, setCategories] = useState<ExpenseCategory[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [editing, setEditing] = useState<ExpenseCategory | null>(null);

  function reload() {
    setLoading(true);
    api
      .listExpenseCategories()
      .then(setCategories)
      .catch((e) => setError(String(e.message || e)))
      .finally(() => setLoading(false));
  }
  useEffect(reload, []);

  async function handleDelete(c: ExpenseCategory) {
    if (!confirm(`Delete "${c.name}"? Transactions already tagged with it keep their amount, just lose the category.`))
      return;
    try {
      await api.deleteExpenseCategory(c.id);
      reload();
    } catch (e: any) {
      alert(e.message || e);
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="font-display text-2xl mb-1">Expense Categories</h1>
          <p className="text-muted text-sm">
            Spending categories used when logging a transaction — separate from the Stock/Bond/Cash
            tag used in Portfolio Allocation.
          </p>
        </div>
        <button
          className="btn-primary"
          onClick={() => {
            setEditing(null);
            setShowForm(true);
          }}
        >
          + New category
        </button>
      </div>

      {showForm && (
        <CategoryForm
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
      ) : categories.length === 0 ? (
        <div className="card p-6 text-muted text-sm">
          No categories yet — create one (e.g. "Groceries", "Bills") before logging transactions.
        </div>
      ) : (
        <ResponsiveTable
          keyFor={(c) => c.id}
          rows={categories}
          columns={
            [
              {
                header: "Name",
                cell: (c) => (
                  <span className="inline-flex items-center gap-2">
                    <span
                      className="inline-block w-2.5 h-2.5 rounded-full shrink-0"
                      style={{ backgroundColor: c.color || "#75694C" }}
                    />
                    {c.name}
                  </span>
                ),
              },
              {
                header: "",
                noMobileLabel: true,
                className: "text-right",
                cell: (c) => (
                  <>
                    <button
                      className="text-brass text-xs"
                      onClick={() => {
                        setEditing(c);
                        setShowForm(true);
                      }}
                    >
                      Edit
                    </button>
                    <button className="text-muted text-xs hover:text-loss ml-3" onClick={() => handleDelete(c)}>
                      Delete
                    </button>
                  </>
                ),
              },
            ] as ResponsiveColumn<ExpenseCategory>[]
          }
        />
      )}
    </div>
  );
}

function CategoryForm({
  initial,
  onDone,
  onCancel,
}: {
  initial: ExpenseCategory | null;
  onDone: () => void;
  onCancel: () => void;
}) {
  const [name, setName] = useState(initial?.name ?? "");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!name.trim()) return;
    setSaving(true);
    setError(null);
    try {
      if (initial) {
        await api.updateExpenseCategory(initial.id, { name: name.trim() });
      } else {
        await api.createExpenseCategory({ name: name.trim() });
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
      <div>
        <label className="text-xs uppercase tracking-wide text-muted block mb-1">Name</label>
        <input
          className="input w-full"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="e.g. Groceries, Bills, Entertainment"
          autoFocus
        />
      </div>
      {!initial && (
        <p className="text-xs text-muted">
          Its color is assigned automatically — chosen to stay visually distinct from every other
          category you've already created.
        </p>
      )}
      {error && <p className="text-loss text-sm">{error}</p>}
      <div className="flex gap-3">
        <button className="btn-primary" disabled={saving}>
          {saving ? "Saving…" : initial ? "Save changes" : "Create category"}
        </button>
        <button type="button" className="btn-ghost" onClick={onCancel}>
          Cancel
        </button>
      </div>
    </form>
  );
}
