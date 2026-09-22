import { describe, it, expect } from "vitest";
import { parseLocaleFloat, formatMoney, formatMoneyPrecise, formatDate, toLocalISODate, formatPct } from "./format";

/**
 * Reading a number a person typed.
 *
 * This function has produced the worst bugs in the app, all of the same
 * kind: not an error, just a different number. `parseFloat` reads as far as
 * it can and ignores the rest, so "1 000 000" came back as 1 and "1.234.567"
 * as 1.234 -- wrong by a factor of a million, accepted in silence, and
 * every caller's isNaN guard says nothing because neither is NaN.
 *
 * So the cases below are mostly about which wrong answers are now refused.
 */
describe("parseLocaleFloat", () => {
  it("reads a plain number", () => {
    expect(parseLocaleFloat("1234")).toBe(1234);
    expect(parseLocaleFloat("1234.56")).toBe(1234.56);
    expect(parseLocaleFloat("0")).toBe(0);
    expect(parseLocaleFloat(" 42 ")).toBe(42);
  });

  it("takes a lone comma as the decimal separator", () => {
    // These are hand-typed amount fields, not pre-formatted figures, so
    // "10,5" means ten and a half rather than one thousand and five.
    expect(parseLocaleFloat("10,5")).toBe(10.5);
    expect(parseLocaleFloat("2,50")).toBe(2.5);
    expect(parseLocaleFloat("0,001")).toBe(0.001);
  });

  it("takes a lone dot the same way", () => {
    expect(parseLocaleFloat("1.234")).toBe(1.234);
  });

  it("resolves both separators by whichever comes last", () => {
    expect(parseLocaleFloat("1.234,56")).toBe(1234.56);
    expect(parseLocaleFloat("1,234.56")).toBe(1234.56);
    expect(parseLocaleFloat("1.234.567,89")).toBe(1234567.89);
    expect(parseLocaleFloat("1,234,567.89")).toBe(1234567.89);
  });

  it("treats a repeated separator as a thousands grouping", () => {
    // A pasted "1.234.567" parsed as 1.234: the right digits, off by a
    // factor of a million, and stored without complaint.
    expect(parseLocaleFloat("1.234.567")).toBe(1234567);
    expect(parseLocaleFloat("1,234,567")).toBe(1234567);
  });

  it("treats a space between digits as a thousands grouping", () => {
    // How French and the Nordic locales write a million, what
    // Intl.NumberFormat emits for them, and what a pasted bank figure looks
    // like. It reached parseFloat as "1 000 000", which stops at the first
    // space and returns 1.
    expect(parseLocaleFloat("1 000 000")).toBe(1000000);
    expect(parseLocaleFloat("1 000 000")).toBe(1000000);   // no-break space
    expect(parseLocaleFloat("1 000 000")).toBe(1000000);   // narrow no-break (fr-FR)
    expect(parseLocaleFloat("1 000")).toBe(1000);               // thin space
    expect(parseLocaleFloat("1'000'000")).toBe(1000000);             // Swiss apostrophe
    expect(parseLocaleFloat("1’000")).toBe(1000);               // typographic apostrophe
  });

  it("combines a grouping space with a decimal comma", () => {
    expect(parseLocaleFloat("1 234,56")).toBe(1234.56);
  });

  it("keeps the sign", () => {
    expect(parseLocaleFloat("-1234,5")).toBe(-1234.5);
    expect(parseLocaleFloat("+1234,5")).toBe(1234.5);
    expect(parseLocaleFloat("-1.234.567")).toBe(-1234567);
  });

  it("reads a bare decimal", () => {
    expect(parseLocaleFloat(".5")).toBe(0.5);
    expect(parseLocaleFloat(",5")).toBe(0.5);
    expect(parseLocaleFloat("5.")).toBe(5);
  });

  it("refuses anything that is not a number all through", () => {
    // parseFloat returned 1.5 for "1.5k" and 10 for the mistyped range
    // "10-20" -- neither is NaN, so no caller could tell.
    for (const input of ["1.5k", "10-20", "250000 euro", "12 34 abc", "abc", "", "   ",
                         "1,2,3.4.5", "--5", "1e", "NaN", "Infinity", "1/2", "€100"]) {
      expect(parseLocaleFloat(input), `"${input}" must be refused`).toBeNaN();
    }
  });

  it("refuses a double-keypress typo instead of guessing", () => {
    // "1..2" became 12 and "1.23.456" became 123456 -- a separator was
    // stripped as a grouping without checking it formed groups of three.
    expect(parseLocaleFloat("1..2")).toBeNaN();
    expect(parseLocaleFloat("1.23.456")).toBeNaN();
    expect(parseLocaleFloat("1,23,456")).toBeNaN();
    expect(parseLocaleFloat("12.34.56")).toBeNaN();
  });

  it("accepts exponent notation", () => {
    expect(parseLocaleFloat("1e3")).toBe(1000);
    expect(parseLocaleFloat("1.5e2")).toBe(150);
  });
});

describe("formatMoney", () => {
  it("shows a dash rather than a fake zero when there is no figure", () => {
    expect(formatMoney(null)).toBe("—");
    expect(formatMoney(undefined)).toBe("—");
    expect(formatMoney(0)).not.toBe("—");
  });

  it("does not throw on a currency code Intl rejects", () => {
    // Intl.NumberFormat throws on anything that is not three letters, and a
    // throw during render unmounts the whole app -- including the page
    // holding the button needed to correct the value.
    for (const code of ["AB", "A", "", "EURO", "12A", "€€€"]) {
      expect(() => formatMoney(1234.5, code)).not.toThrow();
      expect(formatMoney(1234.5, code)).toContain("1,234.5");
    }
  });

  it("formats a valid currency normally", () => {
    expect(formatMoney(1234.5, "EUR")).toContain("1,234.5");
  });
});

describe("formatMoneyPrecise", () => {
  it("keeps more decimals for a value under one unit", () => {
    // A single asset's price or a voucher's unit value can be worth a small
    // fraction of a currency unit; three decimals collapses it to "0.00".
    expect(formatMoneyPrecise(0.000123, "EUR")).not.toMatch(/0\.00\b/);
    expect(formatMoneyPrecise(null)).toBe("—");
  });

  it("is deliberately different from formatMoney", () => {
    expect(formatMoneyPrecise(0.000123, "EUR")).not.toBe(formatMoney(0.000123, "EUR"));
  });
});

describe("dates", () => {
  it("renders a stored date as the day it says, in any timezone", () => {
    // "YYYY-MM-DD" parsed by new Date() is UTC midnight, which lands a day
    // earlier for anyone behind UTC -- all of the Americas.
    expect(formatDate("2026-03-01")).toContain("Mar");
    expect(formatDate("2026-03-01")).toContain("1");
    expect(formatDate("2026-01-01")).toContain("2026");
  });

  it("builds an ISO date from the local calendar, not the UTC one", () => {
    // toISOString() reports the UTC date: near local midnight that is the
    // wrong day, which rejected "today" as a future date east of UTC and
    // defaulted new entries to tomorrow west of it.
    const d = new Date(2026, 2, 1, 23, 30, 0);   // 1 March, local, late evening
    expect(toLocalISODate(d)).toBe("2026-03-01");
    const early = new Date(2026, 0, 1, 0, 15, 0);
    expect(toLocalISODate(early)).toBe("2026-01-01");
  });

  it("pads month and day", () => {
    expect(toLocalISODate(new Date(2026, 0, 5))).toBe("2026-01-05");
  });
});

describe("formatPct", () => {
  it("shows a dash for a missing figure", () => {
    expect(formatPct(null)).toBe("—");
    expect(formatPct(undefined)).toBe("—");
  });

  it("renders with the requested precision", () => {
    expect(formatPct(12.345)).toBe("12.3%");
    expect(formatPct(12.345, 2)).toBe("12.35%");
  });
});
