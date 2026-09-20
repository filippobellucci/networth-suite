/**
 * Formats an amount, tolerating a currency code Intl won't accept.
 *
 * `Intl.NumberFormat` throws a RangeError for anything that isn't three
 * letters, and a throw during render unmounts the entire app -- a single
 * malformed code stored on one account used to blank every page that showed
 * it, including the one with the button needed to correct it. New input is
 * validated server-side now; this keeps any value already in the database
 * from being able to take the UI down.
 */
function formatWithCurrency(value: number, currency: string, maximumFractionDigits: number): string {
  const options: Intl.NumberFormatOptions = { minimumFractionDigits: 0, maximumFractionDigits };
  try {
    return new Intl.NumberFormat("en-US", { style: "currency", currency, ...options }).format(value);
  } catch {
    return `${new Intl.NumberFormat("en-US", options).format(value)} ${currency}`;
  }
}

export function formatMoney(value: number | null | undefined, currency = "EUR"): string {
  if (value === null || value === undefined) return "—";
  return formatWithCurrency(value, currency, 3);
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
  return formatWithCurrency(value, currency, maximumFractionDigits);
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

/**
 * A date as "YYYY-MM-DD" in the viewer's own timezone.
 *
 * `toISOString()` reports the UTC date, not the local one -- near local
 * midnight that is the wrong calendar day for any non-zero UTC offset
 * (rejecting "today" as a future date east of UTC, defaulting new entries to
 * tomorrow west of it, and making "first of this month" land on the last day
 * of the previous one). Building the string from the local
 * getFullYear/getMonth/getDate always agrees with the viewer's calendar.
 */
export function toLocalISODate(d: Date): string {
  const year = d.getFullYear();
  const month = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

export function todayISO(): string {
  return toLocalISODate(new Date());
}

/**
 * Parses a number a person typed by hand, accepting either "." or "," as
 * the decimal separator (plain `parseFloat` only understands ".", so
 * "10,5" silently became 10 -- truncated, not rejected, which is worse
 * than a validation error since nothing looked wrong at entry time).
 *
 * If both separators appear (e.g. "1.234,56" or "1,234.56"), whichever one
 * appears LAST is treated as the decimal point and the other is stripped
 * as a thousands grouping.
 *
 * A separator that appears more than once is always a thousands grouping --
 * no number has two decimal points. Without that rule a pasted
 * "1.234.567" (or "1,234,567") parsed as 1.234: the right digits, off by a
 * factor of a million, and stored without complaint.
 *
 * A single comma is read as the decimal separator ("10,5" -> 10.5) rather
 * than a thousands grouping, since these are plain amount fields typed by
 * hand, not pre-formatted numbers where "1,234" would mean one thousand two
 * hundred thirty-four. A single dot keeps its usual meaning, so "1.234" is
 * likewise 1.234 -- the two are treated alike, and neither can be
 * disambiguated from the text alone.
 */
export function parseLocaleFloat(raw: string): number {
  const trimmed = raw.trim();
  if (!trimmed) return NaN;
  const commas = (trimmed.match(/,/g) || []).length;
  const dots = (trimmed.match(/\./g) || []).length;
  let normalized = trimmed;
  if (commas && dots) {
    normalized =
      trimmed.lastIndexOf(",") > trimmed.lastIndexOf(".")
        ? trimmed.replace(/\./g, "").replace(",", ".")
        : trimmed.replace(/,/g, "");
  } else if (commas > 1 || dots > 1) {
    // Repeated, and the only separator present: grouping, so drop them all.
    normalized = trimmed.replace(/[.,]/g, "");
  } else if (commas === 1) {
    normalized = trimmed.replace(",", ".");
  }
  return parseFloat(normalized);
}
