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

  return (
    <div className="space-y-6">
      <div>
        <h1 className="font-display text-2xl mb-1">Expenses</h1>
        <p className="text-muted text-sm">
          Log an income or expense against a cash account of the selected portfolio — its balance
          everywhere else in the app (Portfolio, Summary, Allocation) updates automatically, and is no
          longer edited by hand. Categories, merchant rules and budgets are this portfolio's own.
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

      {tab === "log" && <Transactions />}
      {tab === "categories" && <ExpenseCategories />}
      {tab === "merchants" && <ExpenseMerchants />}
      {tab === "budgets" && <ExpenseBudgets />}
      {tab === "recurring" && <ExpenseRecurring />}
      {tab === "history" && <ExpenseHistory />}
    </div>
  );
}
