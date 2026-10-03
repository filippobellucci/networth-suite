import type { AllocationCategory } from "../types";
import { ALLOCATION_CATEGORY_LABELS } from "../types";
import { useTheme } from "../context/ThemeContext";
import SnapshotBreakdown from "../components/SnapshotBreakdown";

type CategoryKey = AllocationCategory | "UNCATEGORIZED";

const CATEGORY_LABELS: Record<CategoryKey, string> = {
  ...ALLOCATION_CATEGORY_LABELS,
  UNCATEGORIZED: "Uncategorized",
};

const CATEGORY_COLORS_LIGHT: Record<CategoryKey, string> = {
  STOCK: "#2954FF",
  BOND: "#178A45",
  CASH: "#6B7280",
  EMERGENCY_FUND: "#D97706",
  PENSION_FUND: "#8B5CF6",
  UNCATEGORIZED: "#9CA3AF",
};

const CATEGORY_COLORS_DARK: Record<CategoryKey, string> = {
  STOCK: "#6E8CFF",
  BOND: "#34D399",
  CASH: "#8B93A0",
  EMERGENCY_FUND: "#FBBF24",
  PENSION_FUND: "#A78BFA",
  UNCATEGORIZED: "#6B7280",
};

export default function PortfolioAllocation() {
  const { theme } = useTheme();
  const colors = theme === "dark" ? CATEGORY_COLORS_DARK : CATEGORY_COLORS_LIGHT;

  return (
    <SnapshotBreakdown
      info={
        <>
          <p className="mb-2">
            Stock/Bond/Cash/Emergency Fund/Pension Fund is a <strong>free tag</strong> you set
            per asset or per cash-like balance — it's not locked to which section of the app
            you created the item in.
          </p>
          <p>
            For example, a cash account can be tagged "Emergency Fund" or "Pension Fund"
            instead of plain "Cash", and that tag (not where the account lives) is what
            determines its slice here.
          </p>
        </>
      }
      emptyMessage={
        "No tagged positions or balances yet in this portfolio. Add a tag from the Asset " +
        "Catalogue, or add a Cash / Emergency Fund / Pension Fund balance from the portfolio page."
      }
      groupHeader="Category"
      positionGroup={(p) => p.category ?? "UNCATEGORIZED"}
      cashGroup={(c) => c.category}
      labelOf={(key) => CATEGORY_LABELS[key as CategoryKey]}
      // STOCK's slice deliberately mirrors the chart's accent color (not a
      // coincidence -- see chartTheme.ts), so it follows the chosen palette
      // the same way; the rest of the category map stays fixed.
      colorOf={(key, _i, chart) => (key === "STOCK" ? chart.accent : colors[key as CategoryKey])}
    />
  );
}
