import { describe, it, expect } from "vitest";
import { decodeCsvBytes, parseCsvHeaderRow } from "./csv";

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

describe("decodeCsvBytes", () => {
  const bytes = (values: number[]) => new Uint8Array(values).buffer;

  it("reads a UTF-8 file as UTF-8, dropping a BOM", () => {
    const utf8 = new TextEncoder().encode("\ufeffData;Importo\n01/02/2026;-3,50;Caffè");
    expect(decodeCsvBytes(utf8.buffer as ArrayBuffer)).toEqual({
      text: "Data;Importo\n01/02/2026;-3,50;Caffè",
      encoding: "UTF-8",
    });
  });

  it("reads a Windows-1252 export without mangling accented letters", () => {
    // "Caffè Città" as a Windows-1252 bank export writes it (è 0xE8, à 0xE0).
    // Bytes 0x80-0x9F (€ among them) are left out: Node's decoder reads
    // those as Latin-1, unlike the browsers this runs in.
    const result = decodeCsvBytes(bytes([0x43, 0x61, 0x66, 0x66, 0xe8, 0x20, 0x43, 0x69, 0x74, 0x74, 0xe0]));
    expect(result).toEqual({ text: "Caffè Città", encoding: "Windows-1252" });
  });

  it("treats plain ASCII as UTF-8", () => {
    expect(decodeCsvBytes(bytes([0x44, 0x61, 0x74, 0x65])).encoding).toBe("UTF-8");
  });
});
