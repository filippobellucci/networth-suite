import { describe, it, expect } from "vitest";
import { parseCsvHeaderRow } from "./csv";

describe("parseCsvHeaderRow", () => {
  it("splits a comma header into column names", () => {
    expect(parseCsvHeaderRow("Date,Amount,Description\n01/01/2026,-5,Coffee", ",")).toEqual([
      "Date", "Amount", "Description",
    ]);
  });

  it("splits on whatever delimiter the file actually uses", () => {
    expect(parseCsvHeaderRow("Date;Amount;Description", ";")).toEqual(["Date", "Amount", "Description"]);
  });

  it("strips surrounding quotes and whitespace", () => {
    expect(parseCsvHeaderRow('"Date", "Amount" ,"Description"', ",")).toEqual([
      "Date", "Amount", "Description",
    ]);
  });

  it("only looks at the first line, not the data rows below it", () => {
    expect(parseCsvHeaderRow("Date,Amount\n01/01/2026,-5\n02/01/2026,-6", ",")).toEqual(["Date", "Amount"]);
  });

  it("returns no columns for an empty file", () => {
    expect(parseCsvHeaderRow("", ",")).toEqual([]);
    expect(parseCsvHeaderRow("   \n", ",")).toEqual([]);
  });
});
