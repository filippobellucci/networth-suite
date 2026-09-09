export function formatMoney(value: number | null | undefined, currency = "EUR"): string {
  if (value === null || value === undefined) return "—";
  return new Intl.NumberFormat("en-US", { style: "currency", currency, minimumFractionDigits: 0, maximumFractionDigits: 3 }).format(value);
}

// Kept as a separate export for call-site clarity, but now behaves exactly
// like formatMoney: up to 3 decimals, trimmed to 0 for whole numbers.
export const formatMoneyPrecise = formatMoney;

export function formatDate(value: string): string {
  return new Date(value).toLocaleDateString("en-US", { year: "numeric", month: "short", day: "numeric" });
}

export function formatPct(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined) return "—";
  return `${value.toFixed(digits)}%`;
}

export function todayISO(): string {
  return new Date().toISOString().slice(0, 10);
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
