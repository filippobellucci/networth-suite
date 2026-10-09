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
