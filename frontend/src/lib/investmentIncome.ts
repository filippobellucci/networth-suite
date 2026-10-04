import type { InvestmentIncomeKind, TransactionDirection } from "../types";

/** Mirrors the backend's rule (core-networth's _validate_investment_income): only an
 * INCOME that isn't itself a refund can be marked as a dividend/coupon/interest
 * payment -- see CashTransaction.investment_income_kind. Used to decide whether to
 * show the picker at all, so the form never builds a combination the server would
 * reject. */
export function canMarkInvestmentIncome(direction: TransactionDirection, isRefund: boolean): boolean {
  return direction === "INCOME" && !isRefund;
}

export const INVESTMENT_INCOME_LABELS: Record<InvestmentIncomeKind, string> = {
  DIVIDEND: "Dividend",
  COUPON: "Coupon",
  INTEREST: "Interest",
};
