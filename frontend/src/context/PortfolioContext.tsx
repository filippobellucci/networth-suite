import { createContext, Fragment, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import type { Portfolio } from "../types";
import { errorText } from "../lib/errors";

interface PortfolioContextValue {
  /** The active (non-archived) portfolios, the ones the picker offers. */
  portfolios: Portfolio[];
  /** The portfolio every page shows; null while loading or when there is none. */
  portfolio: Portfolio | null;
  selectPortfolio: (id: string) => void;
  /** Re-reads the list -- after a portfolio is created, archived or restored. */
  reload: () => Promise<void>;
  loading: boolean;
  error: string | null;
}

const PortfolioContext = createContext<PortfolioContextValue | null>(null);

const STORAGE_KEY = "portfolioId";

function storedId(): string {
  try {
    return localStorage.getItem(STORAGE_KEY) ?? "";
  } catch {
    return "";
  }
}

/**
 * The one portfolio the whole app is looking at. Every page reads it from
 * here instead of keeping a picker of its own, so the Summary, Insights and
 * Expenses all show the same portfolio and never a sum of several. The
 * choice is remembered across reloads; when it no longer points at an
 * active portfolio (archived, or a backup restored without it) the first
 * one is shown instead.
 */
export function PortfolioProvider({ children }: { children: ReactNode }) {
  const [portfolios, setPortfolios] = useState<Portfolio[]>([]);
  const [selectedId, setSelectedId] = useState(storedId);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(async () => {
    try {
      setPortfolios(await api.listPortfolios());
      setError(null);
    } catch (e) {
      setError(errorText(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    reload();
  }, [reload]);

  const portfolio = portfolios.find((p) => p.id === selectedId) ?? portfolios[0] ?? null;

  const selectPortfolio = useCallback((id: string) => {
    setSelectedId(id);
    try {
      localStorage.setItem(STORAGE_KEY, id);
    } catch {
      /* not remembered across reloads -- still selected for this session */
    }
  }, []);

  return (
    <PortfolioContext.Provider value={{ portfolios, portfolio, selectPortfolio, reload, loading, error }}>
      {children}
    </PortfolioContext.Provider>
  );
}

export function usePortfolio(): PortfolioContextValue {
  const value = useContext(PortfolioContext);
  if (!value) throw new Error("usePortfolio needs a PortfolioProvider");
  return value;
}

/**
 * Renders `children` once a portfolio is selected, so the pages under it can
 * read it with useSelectedPortfolio; until then, the loading state, the
 * error, or an invitation to create the first portfolio.
 *
 * Keyed on the portfolio: picking another one mounts the page afresh, so no
 * state, list or late response of the previous portfolio can be shown under
 * the new one's name.
 */
export function RequirePortfolio({ children }: { children: ReactNode }) {
  const { portfolio, loading, error } = usePortfolio();
  if (loading) return <div className="text-muted">Loading…</div>;
  if (error)
    return (
      <div className="card p-6 border-loss/40">
        <p className="text-loss font-medium mb-1">Could not load your portfolios</p>
        <p className="text-muted text-sm">{error}</p>
        <p className="text-muted text-sm mt-2">Check that all backend services are running (see "Modules & Status").</p>
      </div>
    );
  if (!portfolio)
    return (
      <div className="card p-6 text-muted text-sm">
        No portfolios yet.{" "}
        <Link to="/portfolios" className="text-brass hover:underline">
          Create one
        </Link>{" "}
        to start tracking your net worth.
      </div>
    );
  return <Fragment key={portfolio.id}>{children}</Fragment>;
}

/** The selected portfolio, for a page rendered inside RequirePortfolio. */
export function useSelectedPortfolio(): Portfolio {
  const { portfolio } = usePortfolio();
  if (!portfolio) throw new Error("useSelectedPortfolio needs a RequirePortfolio around it");
  return portfolio;
}
