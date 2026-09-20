import { formatMoney } from "../lib/format";

export default function NetWorthStat({
  label,
  value,
  currency = "EUR",
  size = "lg",
}: {
  label: string;
  /** null renders "—": a figure that couldn't be loaded must not read as zero. */
  value: number | null;
  currency?: string;
  size?: "lg" | "md";
}) {
  return (
    <div>
      <p className="text-xs uppercase tracking-wide text-muted mb-1">{label}</p>
      <p
        className={`font-display font-medium num ${
          size === "lg" ? "text-5xl" : "text-2xl"
        }`}
      >
        {formatMoney(value, currency)}
      </p>
    </div>
  );
}
