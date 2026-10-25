/**
 * The file's own header row, split on the chosen delimiter -- lets the
 * import mapping offer a dropdown of the file's real column names instead
 * of asking the user to type one by hand. This is NOT a CSV parser: quoted
 * fields containing the delimiter aren't unescaped. That is fine for a
 * header row (plain column names), and the server (`_plan_csv_import`,
 * `csv.DictReader`) does the real, correct parsing of every data row.
 */
export function parseCsvHeaderRow(text: string, delimiter: string): string[] {
  const firstLine = text.split(/\r\n|\r|\n/)[0] ?? "";
  if (!firstLine.trim()) return [];
  return firstLine.split(delimiter).map((h) => h.trim().replace(/^"(.*)"$/, "$1"));
}

/**
 * A chosen file's bytes as text. UTF-8 when the bytes are valid UTF-8 (a
 * leading BOM dropped); otherwise Windows-1252, which is what Italian and
 * most Western European bank exports use. Text in a single-byte encoding
 * with any accented letter is almost never valid UTF-8, so the check is
 * reliable; decoding such a file as UTF-8 turned every "è" into "�", in
 * notes and in the merchant names that merchant rules match on.
 */
export function decodeCsvBytes(bytes: ArrayBuffer): { text: string; encoding: "UTF-8" | "Windows-1252" } {
  try {
    return { text: new TextDecoder("utf-8", { fatal: true }).decode(bytes), encoding: "UTF-8" };
  } catch {
    return { text: new TextDecoder("windows-1252").decode(bytes), encoding: "Windows-1252" };
  }
}
