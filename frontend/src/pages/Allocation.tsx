import { useState } from "react";
import SegmentedControl from "../components/SegmentedControl";
import { useIsMobile } from "../context/ViewModeContext";
import PortfolioAllocation from "./PortfolioAllocation";
import CurrencyExposure from "./CurrencyExposure";
import GeoAllocation from "./GeoAllocation";

type Tab = "category" | "currency" | "geography";

export default function Allocation() {
  const [tab, setTab] = useState<Tab>("category");
  const isMobile = useIsMobile();

  return (
    <div className="space-y-6">
      <div>
        <h1 className="font-display text-2xl mb-1">Allocation</h1>
        <p className="text-muted text-sm">
          How your net worth breaks down — by category, by currency, and by geography.
        </p>
      </div>

      <SegmentedControl
        options={[
          { value: "category", label: "Category" },
          { value: "currency", label: "Currency" },
          { value: "geography", label: "Geography" },
        ]}
        value={tab}
        onChange={setTab}
        className={isMobile ? "w-full" : undefined}
      />

      {tab === "category" && <PortfolioAllocation />}
      {tab === "currency" && <CurrencyExposure />}
      {tab === "geography" && <GeoAllocation />}
    </div>
  );
}
