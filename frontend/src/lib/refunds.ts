import type { CashAccount, CashTransaction } from "../types";

export interface RefundCandidate {
  expense: CashTransaction;
  /** What hasn't been refunded yet, in the expense's own account currency. */
  remaining: number;
  accountName: string;
  accountCurrency: string;
}

/**
 * Expenses eligible to be refunded: real expenses only (no transfer legs,
 * and a refund itself can't be refunded), each annotated with how much of
 * it hasn't been refunded yet -- computed the same way the backend does
 * (sum every linked refund, floor at 0), just so the picker can show it.
 * The ones with something left come first, newest first within each group.
 *
 * The refunds are added up in one pass over `transactions`: looking each
 * expense's refunds up in the whole list was quadratic, and ran on every
 * keystroke in the form.
 *
 * `accounts` includes archived ones: an expense may sit on an account that
 * has since been removed, which the active-only list cannot resolve.
 */
export function refundCandidates(transactions: CashTransaction[], accounts: CashAccount[]): RefundCandidate[] {
  const refunded = new Map<string, number>();
  for (const t of transactions) {
    if (t.refund_of_id) refunded.set(t.refund_of_id, (refunded.get(t.refund_of_id) ?? 0) + t.amount);
  }
  const accountById = new Map(accounts.map((a) => [a.id, a]));
  return transactions
    .filter((t) => t.direction === "EXPENSE" && !t.transfer_id && !t.refund_of_id)
    .map((expense) => {
      const remaining = Math.max(0, expense.amount - (refunded.get(expense.id) ?? 0));
      const account = accountById.get(expense.account_id);
      // The backend nets a refund against its expense as raw numbers, with
      // no FX conversion (compute_refund_adjustments in core-networth) --
      // so `expense.amount`/`remaining` are always in the ORIGINAL
      // expense's own account currency, regardless of which account the
      // refund income is logged against. Marked as removed so it's clear
      // why this account isn't in the picker at the top of the form.
      const accountName = account ? (account.archived_at ? `${account.name} (removed)` : account.name) : "";
      return { expense, remaining, accountName, accountCurrency: account?.currency ?? "EUR" };
    })
    .sort(
      (a, b) =>
        (b.remaining > 0 ? 1 : 0) - (a.remaining > 0 ? 1 : 0) || b.expense.entry_date.localeCompare(a.expense.entry_date)
    );
}
