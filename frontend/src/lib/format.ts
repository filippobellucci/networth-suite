export function formatMoney(value: number | null | undefined, currency = "EUR"): string {
  if (value === null || value === undefined) return "—";
  return new Intl.NumberFormat("en-US", { style: "currency", currency, minimumFractionDigits: 0, maximumFractionDigits: 3 }).format(value);
}

// A single asset's price or a voucher's unit value can be worth a small
// fraction of a currency unit -- formatMoney's 3-decimal cap (fine for a
// whole position's aggregate money value) silently collapses anything
// under half a cent to "0.00", hiding the real number. Used by
// NetWorthChart (formatMoney: an aggregate net-worth total, where 3
// decimals is already more than enough) vs. AssetPriceChart
// (formatMoneyPrecise: a single asset's price) -- a real, deliberate
// difference, not something to collapse into one shared formatter.
export function formatMoneyPrecise(value: number | null | undefined, currency = "EUR"): string {
  if (value === null || value === undefined) return "—";
  const maximumFractionDigits = Math.abs(value) > 0 && Math.abs(value) < 1 ? 6 : 3;
  return new Intl.NumberFormat("en-US", { style: "currency", currency, minimumFractionDigits: 0, maximumFractionDigits }).format(value);
}

export function formatDate(value: string): string {
  // A bare "YYYY-MM-DD" date (what entry_date/snapshot_date always are) is
  // parsed by `new Date(string)` as UTC midnight -- rendered back in the
  // browser's local timezone, that lands one calendar day EARLIER than
  // intended for anyone behind UTC (all of the Americas). Build the Date
  // from its year/month/day parts directly instead, which the Date
  // constructor always treats as local time, so the displayed day always
  // matches the stored one regardless of the viewer's timezone.
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(value);
  const parsed = match
    ? new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]))
    : new Date(value);
  return parsed.toLocaleDateString("en-US", { year: "numeric", month: "short", day: "numeric" });
}

export function formatPct(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined) return "—";
  return `${value.toFixed(digits)}%`;
}

export function todayISO(): string {
  // `toISOString()` reports the UTC date, not the viewer's local date --
  // near local midnight this is the wrong calendar day for any non-zero
  // UTC offset (rejects "today" as a future date east of UTC; silently
  // defaults new entries to tomorrow west of UTC). Build the string from
  // local getFullYear/getMonth/getDate instead, which always agree with
  // what the viewer's own calendar shows.
  const d = new Date();
  const year = d.getFullYear();
  const month = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

/**
 * Parses a number a person typed by hand, accepting either "." or "," as
 * the decimal separator (plain `parseFloat` only understands ".", so
 * "10,5" silently became 10 -- truncated, not rejected, which is worse
 * than a validation error since nothing looked wrong at entry time).
 *
 * If both separators appear (e.g. "1.234,56" or "1,234.56"), whichever one
 * appears LAST is treated as the decimal point and the other is stripped
 * as a thousands grouping. If only commas appear, every comma is treated
 * as the decimal separator ("10,5" -> 10.5) rather than a thousands
 * grouping, since these are plain amount fields typed by hand, not
 * pre-formatted numbers where "1,234" would mean one thousand two hundred
 * thirty-four.
 */
export function parseLocaleFloat(raw: string): number {
  const trimmed = raw.trim();
  if (!trimmed) return NaN;
  const hasComma = trimmed.includes(",");
  const hasDot = trimmed.includes(".");
  let normalized = trimmed;
  if (hasComma && hasDot) {
    const lastComma = trimmed.lastIndexOf(",");
    const lastDot = trimmed.lastIndexOf(".");
    normalized = lastComma > lastDot ? trimmed.replace(/\./g, "").replace(",", ".") : trimmed.replace(/,/g, "");
  } else if (hasComma) {
    normalized = trimmed.replace(",", ".");
  }
  return parseFloat(normalized);
}
