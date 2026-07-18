import { formatMoney } from "../lib/format";

export default function NetWorthStat({
  label,
  value,
  currency = "EUR",
  size = "lg",
}: {
  label: string;
  value: number;
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
