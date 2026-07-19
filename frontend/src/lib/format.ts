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
