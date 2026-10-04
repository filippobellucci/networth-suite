import { describe, expect, it } from "vitest";
import { canMarkInvestmentIncome } from "./investmentIncome";

describe("canMarkInvestmentIncome", () => {
  it("allows it on a plain income", () => {
    expect(canMarkInvestmentIncome("INCOME", false)).toBe(true);
  });

  it("refuses it on an expense -- the backend only accepts it on an INCOME", () => {
    expect(canMarkInvestmentIncome("EXPENSE", false)).toBe(false);
  });

  it("refuses it on a refund -- mutually exclusive with refund_of_id on the backend", () => {
    expect(canMarkInvestmentIncome("INCOME", true)).toBe(false);
  });
});
