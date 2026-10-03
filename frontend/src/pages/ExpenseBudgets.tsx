import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { Budget, BudgetProgress, BudgetProgressItem, ExpenseCategory } from "../types";
import { formatMoney, parseLocaleFloat, toLocalISODate } from "../lib/format";
import { errorText } from "../lib/errors";

function monthKey(d: Date): string {
  return toLocalISODate(d).slice(0, 7);
}

function monthTitle(key: string): string {
  const [y, m] = key.split("-").map(Number);
  return new Date(y, m - 1, 1).toLocaleDateString("en-US", { month: "long", year: "numeric" });
}

const STATUS_TEXT: Record<BudgetProgressItem["status"], string> = {
  OK: "On track",
  NEAR: "Almost used up",
  OVER: "Over budget",
};

/**
 * Monthly spending limits per category, and how this (or a past) month is
 * going against them. The thin vertical line on each bar is how much of the
 * month has passed: spending ahead of it is spending faster than the budget
 * allows, whatever the percentage says.
 */
export default function ExpenseBudgets() {
  const [categories, setCategories] = useState<ExpenseCategory[]>([]);
  const [budgets, setBudgets] = useState<Budget[]>([]);
  const [month, setMonth] = useState(monthKey(new Date()));
  const [progress, setProgress] = useState<BudgetProgress | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [newCategory, setNewCategory] = useState("");
  const [newAmount, setNewAmount] = useState("");
  const [editing, setEditing] = useState<{ id: string; amount: string } | null>(null);

  function reload() {
    setError(null);
    Promise.all([api.listExpenseCategories(), api.listBudgets(), api.getBudgetProgress(month)])
      .then(([c, b, p]) => {
        setCategories(c);
        setBudgets(b);
        setProgress(p);
      })
      .catch((e) => setError(errorText(e)));
  }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(reload, [month]);

  const now = new Date();
  const thisMonth = monthKey(now);
  const shiftMonth = (delta: number) => {
    const [y, m] = month.split("-").map(Number);
    setMonth(monthKey(new Date(y, m - 1 + delta, 1)));
  };

  async function run(action: () => Promise<unknown>) {
    setError(null);
    try {
      await action();
      reload();
    } catch (e) {
      setError(errorText(e));
    }
  }

  function addBudget(e: React.FormEvent) {
    e.preventDefault();
    const amount = parseLocaleFloat(newAmount);
    if (!newCategory || isNaN(amount) || amount <= 0) {
      setError("Pick a category and enter a positive monthly amount.");
      return;
    }
    run(async () => {
      await api.createBudget({ category_id: newCategory, amount });
      setNewCategory("");
      setNewAmount("");
    });
  }

  function saveEdit(e: React.FormEvent) {
    e.preventDefault();
    if (!editing) return;
    const amount = parseLocaleFloat(editing.amount);
    if (isNaN(amount) || amount <= 0) {
      setError("Enter a positive monthly amount.");
      return;
    }
    run(async () => {
      await api.updateBudget(editing.id, { amount });
      setEditing(null);
    });
  }

  const withBudget = new Set(budgets.map((b) => b.category_id));
  const available = categories.filter((c) => !withBudget.has(c.id));
  const colorOf = (id: string) => categories.find((c) => c.id === id)?.color || "#9CA3AF";

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <p className="text-muted text-sm max-w-xl">
          A monthly limit per category, across all your portfolios. Spending is counted like everywhere else in Expenses: transfers between your
          accounts don't count, and refunds reduce what they refund.
        </p>
        <div className="flex items-center gap-2" aria-label="Month">
          <button className="btn-ghost text-sm" onClick={() => shiftMonth(-1)} aria-label="Previous month">
            ←
          </button>
          <span className="text-sm min-w-[9rem] text-center">{monthTitle(month)}</span>
          <button
            className="btn-ghost text-sm"
            onClick={() => shiftMonth(1)}
            disabled={month >= thisMonth}
            aria-label="Next month"
          >
            →
          </button>
        </div>
      </div>

      {error && <p className="text-loss text-sm">{error}</p>}

      {progress && progress.items.length === 0 ? (
        <div className="card p-6 text-muted text-sm">No budgets yet — add one below.</div>
      ) : (
        progress && (
          <div className="card" aria-label="Budgets">
            {progress.items.map((item) => {
              const fill = Math.min(item.percent, 100);
              const barColor =
                item.status === "OVER" ? "var(--color-loss)" : item.status === "NEAR" ? "#D97706" : "var(--color-brass)";
              const isEditing = editing?.id === item.budget_id;
              return (
                <div
                  key={item.budget_id}
                  className="p-4 space-y-2 border-t ledger-rule first:border-t-0"
                  aria-label={`Budget ${item.category_name}`}
                >
                  <div className="flex items-baseline justify-between gap-3 flex-wrap">
                    <span className="inline-flex items-center gap-2 font-medium">
                      <span className="inline-block w-2.5 h-2.5 rounded-full" style={{ backgroundColor: colorOf(item.category_id) }} />
                      {item.category_name}
                    </span>
                    <span className="text-sm num">
                      {formatMoney(item.spent, item.currency)} <span className="text-muted">of</span>{" "}
                      {formatMoney(item.budget, item.currency)}
                    </span>
                  </div>
                  <div className="relative h-2.5 rounded-full bg-ink-raised overflow-hidden" role="meter"
                    aria-valuemin={0} aria-valuemax={item.budget} aria-valuenow={item.spent}
                    aria-label={`${item.category_name}: ${item.percent}% of the budget used`}>
                    <div className="h-full rounded-full" style={{ width: `${fill}%`, backgroundColor: barColor }} />
                    {progress.elapsed_pct > 0 && progress.elapsed_pct < 100 && (
                      <div
                        className="absolute top-0 h-full w-0.5 bg-ink-text opacity-60"
                        style={{ left: `${progress.elapsed_pct}%` }}
                        title={`${progress.elapsed_pct}% of the month has passed`}
                      />
                    )}
                  </div>
                  <div className="flex items-center justify-between gap-3 flex-wrap text-xs">
                    <span className={item.status === "OVER" ? "text-loss font-medium" : item.status === "NEAR" ? "font-medium" : "text-muted"}>
                      {item.status === "OVER" ? "▲ " : item.status === "NEAR" ? "● " : ""}
                      {STATUS_TEXT[item.status]} · {item.percent}%{" "}
                      {item.remaining >= 0
                        ? `· ${formatMoney(item.remaining, item.currency)} left`
                        : `· ${formatMoney(-item.remaining, item.currency)} over`}
                    </span>
                    {isEditing ? (
                      <form onSubmit={saveEdit} className="inline-flex items-center gap-2">
                        <input
                          className="input text-xs w-24"
                          inputMode="decimal"
                          value={editing.amount}
                          onChange={(e) => setEditing({ id: item.budget_id, amount: e.target.value })}
                          aria-label="Monthly amount"
                          autoFocus
                        />
                        <button className="text-brass">Save</button>
                        <button type="button" className="text-muted" onClick={() => setEditing(null)}>
                          Cancel
                        </button>
                      </form>
                    ) : (
                      <span className="inline-flex gap-3">
                        <button className="text-brass" onClick={() => setEditing({ id: item.budget_id, amount: String(item.budget) })}>
                          Edit
                        </button>
                        <button
                          className="text-muted hover:text-loss"
                          onClick={() =>
                            confirm(`Remove the budget for "${item.category_name}"?`) &&
                            run(() => api.deleteBudget(item.budget_id))
                          }
                        >
                          Remove
                        </button>
                      </span>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        )
      )}

      <form onSubmit={addBudget} className="card p-4 flex flex-wrap items-end gap-3" aria-label="Add budget">
        <div className="flex-1 min-w-[10rem]">
          <label className="field-label">Category</label>
          <select className="input w-full" value={newCategory} onChange={(e) => setNewCategory(e.target.value)}>
            <option value="">{available.length ? "Pick a category…" : "Every category has a budget"}</option>
            {available.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </select>
        </div>
        <div className="w-40">
          <label className="field-label">Per month (EUR)</label>
          <input className="input w-full" inputMode="decimal" value={newAmount} onChange={(e) => setNewAmount(e.target.value)} placeholder="e.g. 300" />
        </div>
        <button className="btn-primary" disabled={!available.length}>
          Add budget
        </button>
      </form>
    </div>
  );
}
