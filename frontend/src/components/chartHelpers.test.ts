import { describe, it, expect, afterEach, vi } from "vitest";
import { cutoffFor, toPercentage, formatPctTick } from "./chartHelpers";

/**
 * The chart's range windows and its percentage mode.
 *
 * "Month" used setMonth(getMonth() - 1), which on 31 March lands on 3 March
 * because there is no 31 February -- so on the last days of long months the
 * window was 28 days short and disagreed with the badge beside it, which
 * comes from the backend's own correctly clamped calculation.
 */
describe("cutoffFor", () => {
  afterEach(() => vi.useRealTimers());

  const at = (iso: string) => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date(iso));
  };

  it("has no cutoff for the whole history", () => {
    at("2026-03-31T12:00:00");
    expect(cutoffFor("MAX")).toBeNull();
  });

  it("goes back one day, one week", () => {
    at("2026-03-31T12:00:00");
    expect(cutoffFor("D")!.getDate()).toBe(30);
    expect(cutoffFor("W")!.getDate()).toBe(24);
  });

  it("clamps the day when the previous month is shorter", () => {
    at("2026-03-31T12:00:00");
    const month = cutoffFor("M")!;
    expect(month.getMonth()).toBe(1);        // February
    expect(month.getDate()).toBe(28);        // not 3 March
  });

  it("clamps into a leap February too", () => {
    at("2024-03-31T12:00:00");
    const month = cutoffFor("M")!;
    expect(month.getMonth()).toBe(1);
    expect(month.getDate()).toBe(29);
  });

  it("crosses a year boundary", () => {
    at("2026-01-15T12:00:00");
    const month = cutoffFor("M")!;
    expect(month.getFullYear()).toBe(2025);
    expect(month.getMonth()).toBe(11);       // December

    const year = cutoffFor("Y")!;
    expect(year.getFullYear()).toBe(2025);
    expect(year.getMonth()).toBe(0);
  });

  it("never lands in the same month it started in", () => {
    for (const day of ["2026-01-31", "2026-03-31", "2026-05-31", "2026-07-31",
                       "2026-08-31", "2026-10-31", "2026-12-31"]) {
      at(`${day}T12:00:00`);
      const now = new Date(`${day}T12:00:00`);
      const month = cutoffFor("M")!;
      expect(month.getMonth(), day).not.toBe(now.getMonth());
      vi.useRealTimers();
    }
  });
});

describe("toPercentage", () => {
  it("expresses every point as a change from the first", () => {
    const rows = toPercentage([{ value: 100 }, { value: 110 }, { value: 90 }]);
    expect(rows.map((r) => r.value)).toEqual([0, 10, -10]);
  });

  it("leaves an empty series alone", () => {
    expect(toPercentage([])).toEqual([]);
  });

  it("does not divide by a zero starting point", () => {
    // A portfolio that started at nothing has no percentage change to show;
    // dividing anyway produces Infinity, which is not renderable.
    const rows = toPercentage([{ value: 0 }, { value: 50 }]);
    expect(rows.every((r) => Number.isFinite(r.value))).toBe(true);
    expect(rows.map((r) => r.value)).toEqual([0, 0]);
  });

  it("keeps the other fields on each point", () => {
    const rows = toPercentage([{ value: 100, date: "2026-01-01" }, { value: 150, date: "2026-01-02" }]);
    expect(rows[1]).toMatchObject({ date: "2026-01-02", value: 50 });
  });
});

describe("formatPctTick", () => {
  it("signs a gain and leaves a loss with its own minus", () => {
    expect(formatPctTick(12.34)).toBe("+12.3%");
    expect(formatPctTick(-12.34)).toBe("-12.3%");
    expect(formatPctTick(0)).toBe("+0.0%");
  });
});
