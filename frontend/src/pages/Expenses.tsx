import { useState } from "react";
import SegmentedControl from "../components/SegmentedControl";
import { useIsMobile } from "../context/ViewModeContext";
import Transactions from "./Transactions";
import ExpenseCategories from "./ExpenseCategories";
import ExpenseHistory from "./ExpenseHistory";

type Tab = "log" | "categories" | "history";

export default function Expenses() {
  const [tab, setTab] = useState<Tab>("log");
  const isMobile = useIsMobile();

  return (
    <div className="space-y-6">
      <div>
        <h1 className="font-display text-2xl mb-1">Expenses</h1>
        <p className="text-muted text-sm">
          Log an income or expense against a cash account — its balance everywhere else in the app
          (Portfolio, Summary, Allocation) updates automatically, and is no longer edited by hand.
        </p>
      </div>

      <SegmentedControl
        options={[
          { value: "log", label: "Log" },
          { value: "categories", label: "Categories" },
          { value: "history", label: "History" },
        ]}
        value={tab}
        onChange={setTab}
        className={isMobile ? "w-full" : undefined}
      />

      {tab === "log" && <Transactions />}
      {tab === "categories" && <ExpenseCategories />}
      {tab === "history" && <ExpenseHistory />}
    </div>
  );
}
