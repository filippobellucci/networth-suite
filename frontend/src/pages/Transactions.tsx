import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { Portfolio, CashAccount, ExpenseCategory, CashTransaction } from "../types";
import TransactionLogForm from "../components/TransactionLogForm";
import TransactionList from "../components/TransactionList";

interface TransactionsProps {
  /** Lifted up to Expenses.tsx so the selected portfolio is shared across
   * the Log/Categories/History tabs instead of resetting when switching
   * tabs. */
  portfolioId: string;
  onPortfolioIdChange: (id: string) => void;
}

export default function Transactions({ portfolioId, onPortfolioIdChange }: TransactionsProps) {
  const [portfolios, setPortfolios] = useState<Portfolio[]>([]);
  const [accounts, setAccounts] = useState<CashAccount[]>([]);
  /** Same portfolio, archived ones included — used only to label existing
   * rows (see the refund picker), never to offer somewhere to log to. */
  const [allAccounts, setAllAccounts] = useState<CashAccount[]>([]);
  const [categories, setCategories] = useState<ExpenseCategory[]>([]);
  const [portfolioTransactions, setPortfolioTransactions] = useState<CashTransaction[]>([]);
  const [accountId, setAccountId] = useState("");
  // Bumped whenever the log form creates a transaction, so the recent list
  // (which owns its own fetch) knows to refetch.
  const [recentReloadKey, setRecentReloadKey] = useState(0);

  useEffect(() => {
    api.listPortfolios().then((list) => {
      setPortfolios(list);
      if (!portfolioId && list.length > 0) onPortfolioIdChange(list[0].id);
    });
    api.listExpenseCategories().then(setCategories);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function refreshPortfolioTransactions() {
    api.listTransactions({ portfolio_id: portfolioId }).then(setPortfolioTransactions).catch(() => {});
  }

  useEffect(() => {
    if (!portfolioId) return;
    // Two lists on purpose. The pickers below must only ever offer accounts
    // you can still log against, but the refund picker DESCRIBES expenses
    // that already exist -- and an expense on a since-removed account is
    // still refundable (the backend only requires the refund to land in the
    // same portfolio and the same currency), and needs its account's name
    // and currency.
    api.listCashAccounts(portfolioId, true).then(setAllAccounts).catch(() => setAllAccounts([]));
    api.listCashAccounts(portfolioId).then((list) => {
      // Pension Fund accounts stay hand-updated only (see PortfolioDetail) --
      // never offered here, so they can't accidentally end up managed by
      // both the manual "Update" flow and the transaction ledger at once.
      const eligible = list.filter((a) => a.category !== "PENSION_FUND");
      setAccounts(eligible);
      setAccountId((current) => (eligible.some((a) => a.id === current) ? current : eligible[0]?.id ?? ""));
    });
    api.listTransactions({ portfolio_id: portfolioId }).then(setPortfolioTransactions);
  }, [portfolioId]);

  // Transfers don't support voucher accounts (see the backend's /transfers
  // rejection) -- a separate, narrower list for the "From"/"To" pickers, and
  // for converting an income/expense into a transfer.
  const transferAccounts = accounts.filter((a) => a.kind !== "VOUCHER");
  const selectedAccount = accounts.find((a) => a.id === accountId);

  return (
    <div className="space-y-8">
      <TransactionLogForm
        portfolios={portfolios}
        portfolioId={portfolioId}
        onPortfolioIdChange={onPortfolioIdChange}
        accounts={accounts}
        accountId={accountId}
        onAccountIdChange={setAccountId}
        transferAccounts={transferAccounts}
        allAccounts={allAccounts}
        portfolioTransactions={portfolioTransactions}
        categories={categories}
        selectedAccount={selectedAccount}
        onLogged={() => {
          refreshPortfolioTransactions();
          setRecentReloadKey((k) => k + 1);
        }}
      />

      {selectedAccount && (
        <TransactionList
          selectedAccount={selectedAccount}
          categories={categories}
          transferAccounts={transferAccounts}
          accountId={accountId}
          reloadKey={recentReloadKey}
          onTransactionsChanged={refreshPortfolioTransactions}
        />
      )}
    </div>
  );
}
