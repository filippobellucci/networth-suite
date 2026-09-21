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

const GROUPING_SEPARATORS = "[\\s\\u00A0\\u202F\\u2009'\\u2019]";
const FULLY_NUMERIC = /^[+-]?(\d+(\.\d*)?|\.\d+)([eE][+-]?\d+)?$/;

/**
 * Whether `s` really is digits split into thousands by `sep` -- 1 to 3 digits,
 * then groups of exactly 3. Stripping a repeated separator without checking
 * this turned the double-keypress typo "1..2" into 12, and "1.23.456" into
 * 123456: wrong by a factor of ten or more, and not NaN, so silent.
 */
function isThousandsGrouped(s: string, sep: "." | ","): boolean {
  const esc = sep === "." ? "\\." : ",";
  return new RegExp(`^[+-]?\\d{1,3}(${esc}\\d{3})+$`).test(s);
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
 *
 * A space between digits is a thousands grouping too. That is how French and
 * the Nordic locales write a million, and it is what `Intl.NumberFormat`
 * itself emits for them (fr-FR uses U+202F, a narrow no-break space), so it
 * is what a pasted bank figure looks like. Without this "1 000 000" reached
 * `parseFloat` as "1 000 000", which stops at the first space and returns 1 --
 * a million-fold error, accepted in silence. The Swiss apostrophe grouping
 * ("1'000'000") goes the same way; an apostrophe is never a decimal point.
 *
 * Whatever is left must then be a number ALL THROUGH. `parseFloat` reads as
 * far as it can and ignores the rest, so "1.5k" came back as 1.5 and a
 * mistyped range "10-20" as 10 -- neither is NaN, so no caller could tell
 * anything had gone wrong. Returning NaN for input that is not wholly a
 * number is what lets every caller show the error it already has a branch
 * for. The cost is that trailing text which used to be silently ignored
 * ("250000 euro") is now refused rather than guessed at, which for a figure
 * that lands in a net worth total is the better of the two.
 */
export function parseLocaleFloat(raw: string): number {
  const trimmed = raw.trim();
  if (!trimmed) return NaN;
  // Only BETWEEN digits: a space anywhere else is not a grouping mark, and
  // collapsing it would turn "250000 euro" into something that looks numeric.
  const grouped = trimmed.replace(new RegExp(`(\\d)${GROUPING_SEPARATORS}+(?=\\d)`, "g"), "$1");
  const commas = (grouped.match(/,/g) || []).length;
  const dots = (grouped.match(/\./g) || []).length;
  let normalized = grouped;
  if (commas && dots) {
    // Both present: the one that appears LAST is the decimal point, and the
    // other has to be a well-formed grouping of the integer part.
    const commaIsDecimal = grouped.lastIndexOf(",") > grouped.lastIndexOf(".");
    const cut = grouped.lastIndexOf(commaIsDecimal ? "," : ".");
    if (!isThousandsGrouped(grouped.slice(0, cut), commaIsDecimal ? "." : ",")) return NaN;
    normalized = commaIsDecimal
      ? grouped.replace(/\./g, "").replace(",", ".")
      : grouped.replace(/,/g, "");
  } else if (commas > 1 || dots > 1) {
    // Repeated, and the only separator present: grouping, so drop them all --
    // but only once the shape confirms that is what they are.
    if (!isThousandsGrouped(grouped, commas > 1 ? "," : ".")) return NaN;
    normalized = grouped.replace(/[.,]/g, "");
  } else if (commas === 1) {
    normalized = grouped.replace(",", ".");
  }
  if (!FULLY_NUMERIC.test(normalized)) return NaN;
  return parseFloat(normalized);
}
