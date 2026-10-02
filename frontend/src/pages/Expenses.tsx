import { useState } from "react";
import SegmentedControl from "../components/SegmentedControl";
import BankSyncAlerts from "../components/BankSyncAlerts";
import { useIsMobile } from "../context/ViewModeContext";
import Transactions from "./Transactions";
import ExpenseCategories from "./ExpenseCategories";
import ExpenseHistory from "./ExpenseHistory";
import ExpenseMerchants from "./ExpenseMerchants";
import ExpenseBudgets from "./ExpenseBudgets";
import ExpenseRecurring from "./ExpenseRecurring";
import BudgetAlerts from "../components/BudgetAlerts";

type Tab = "log" | "categories" | "merchants" | "budgets" | "recurring" | "history";

export default function Expenses() {
  const [tab, setTab] = useState<Tab>("log");
  const isMobile = useIsMobile();
  // Shared across the Log/History tabs (Categories has no portfolio filter
  // of its own) so switching tabs doesn't reset which portfolio is selected.
  const [portfolioId, setPortfolioId] = useState("");

  return (
    <div className="space-y-6">
      <div>
        <h1 className="font-display text-2xl mb-1">Expenses</h1>
        <p className="text-muted text-sm">
          Log an income or expense against a cash account — its balance everywhere else in the app
          (Portfolio, Summary, Allocation) updates automatically, and is no longer edited by hand.
        </p>
      </div>

      <BankSyncAlerts />
      {tab !== "budgets" && <BudgetAlerts onOpen={() => setTab("budgets")} />}

      <SegmentedControl
        options={[
          { value: "log", label: "Log" },
          { value: "categories", label: "Categories" },
          { value: "merchants", label: "Merchants" },
          { value: "budgets", label: "Budgets" },
          { value: "recurring", label: "Recurring" },
          { value: "history", label: "History" },
        ]}
        value={tab}
        onChange={setTab}
        className={isMobile ? "w-full" : undefined}
      />

      {tab === "log" && <Transactions portfolioId={portfolioId} onPortfolioIdChange={setPortfolioId} />}
      {tab === "categories" && <ExpenseCategories />}
      {tab === "merchants" && <ExpenseMerchants />}
      {tab === "budgets" && <ExpenseBudgets />}
      {tab === "recurring" && <ExpenseRecurring portfolioId={portfolioId} onPortfolioIdChange={setPortfolioId} />}
      {tab === "history" && <ExpenseHistory portfolioId={portfolioId} onPortfolioIdChange={setPortfolioId} />}
    </div>
  );
}
