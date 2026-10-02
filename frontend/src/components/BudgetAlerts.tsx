import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { BudgetProgressItem } from "../types";
import { formatMoney } from "../lib/format";

/**
 * This month's budgets that are used up or nearly so -- shown at the top of
 * Expenses so it doesn't take opening the Budgets tab to find out. Nothing
 * when every budget is on track, or none is set.
 */
export default function BudgetAlerts({ onOpen }: { onOpen?: () => void }) {
  const [items, setItems] = useState<BudgetProgressItem[]>([]);

  useEffect(() => {
    let cancelled = false;
    api
      .getBudgetProgress()
      .then((p) => !cancelled && setItems(p.items.filter((i) => i.status !== "OK")))
      .catch(() => {}); // a convenience banner: the Budgets tab reports its own errors
    return () => {
      cancelled = true;
    };
  }, []);

  if (items.length === 0) return null;
  const over = items.filter((i) => i.status === "OVER");
  const near = items.filter((i) => i.status === "NEAR");
  const describe = (i: BudgetProgressItem) =>
    `${i.category_name} (${formatMoney(i.spent, i.currency)} of ${formatMoney(i.budget, i.currency)})`;

  return (
    <div
      role="alert"
      aria-label="Budget alerts"
      className={`card p-4 text-sm flex items-start justify-between gap-4 flex-wrap ${over.length ? "border-loss/40 text-loss" : ""}`}
    >
      <span>
        {over.length > 0 && <>▲ Over budget this month: {over.map(describe).join(", ")}. </>}
        {near.length > 0 && <>● Almost used up: {near.map(describe).join(", ")}.</>}
      </span>
      {onOpen && (
        <button className="text-brass text-xs font-medium whitespace-nowrap underline" onClick={onOpen}>
          See budgets
        </button>
      )}
    </div>
  );
}
