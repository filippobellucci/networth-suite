import { describe, expect, it } from "vitest";
import type { CashAccount, CashTransaction } from "../types";
import { refundCandidates } from "./refunds";

const eur: CashAccount = { id: "a", portfolio_id: "p", name: "Revolut", currency: "EUR", kind: "CURRENCY" };
const closed: CashAccount = { ...eur, id: "b", name: "Old bank", currency: "USD", archived_at: "2026-01-01T00:00:00" };

function txn(over: Partial<CashTransaction>): CashTransaction {
  return { id: "x", account_id: "a", entry_date: "2026-03-01", direction: "EXPENSE", amount: 10, ...over };
}

describe("refundCandidates", () => {
  it("nets every refund against its expense, floored at zero", () => {
    const list = refundCandidates(
      [
        txn({ id: "e1", amount: 100 }),
        txn({ id: "r1", direction: "INCOME", amount: 30, refund_of_id: "e1" }),
        txn({ id: "r2", direction: "INCOME", amount: 25, refund_of_id: "e1" }),
        txn({ id: "e2", amount: 20, entry_date: "2026-03-05" }),
        txn({ id: "r3", direction: "INCOME", amount: 50, refund_of_id: "e2" }),
      ],
      [eur]
    );
    expect(list.map((c) => [c.expense.id, c.remaining])).toEqual([
      ["e1", 45],
      ["e2", 0],
    ]);
  });

  it("offers neither a transfer leg, a refund nor an income", () => {
    const list = refundCandidates(
      [
        txn({ id: "leg", transfer_id: "t" }),
        txn({ id: "refund", direction: "INCOME", refund_of_id: "e" }),
        txn({ id: "salary", direction: "INCOME" }),
        txn({ id: "e" }),
      ],
      [eur]
    );
    expect(list.map((c) => c.expense.id)).toEqual(["e"]);
  });

  it("puts what still has something to refund first, newest first", () => {
    const list = refundCandidates(
      [
        txn({ id: "old", entry_date: "2026-01-01" }),
        txn({ id: "done", entry_date: "2026-04-01" }),
        txn({ id: "back", direction: "INCOME", refund_of_id: "done" }),
        txn({ id: "new", entry_date: "2026-03-01" }),
      ],
      [eur]
    );
    expect(list.map((c) => c.expense.id)).toEqual(["new", "old", "done"]);
  });

  it("names a removed account as such, in that account's own currency", () => {
    const [c] = refundCandidates([txn({ id: "e", account_id: "b" })], [eur, closed]);
    expect([c.accountName, c.accountCurrency]).toEqual(["Old bank (removed)", "USD"]);
  });
});
