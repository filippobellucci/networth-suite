import { useEffect, useState, type DependencyList } from "react";
import { api } from "../api/client";
import type { Portfolio, PortfolioSnapshot } from "../types";

/**
 * Runs `fetcher` whenever `deps` change and keeps only the newest result --
 * a slower request for the selection just switched away from can't land
 * after a faster one for the current selection and display stale data under
 * the current label. A null `fetcher` means "nothing to fetch yet" (no
 * selection): the last value is left as-is, exactly like the early `return`
 * this replaces. A failed fetch clears the value.
 */
export function useLatestFetch<T>(fetcher: (() => Promise<T>) | null, deps: DependencyList): T | null {
  const [value, setValue] = useState<T | null>(null);

  useEffect(() => {
    if (!fetcher) return;
    let cancelled = false;
    fetcher()
      .then((result) => !cancelled && setValue(result))
      .catch(() => !cancelled && setValue(null));
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  return value;
}

/**
 * The portfolio list plus which one is currently selected, defaulting to the
 * first one once the list arrives. Shared by every page that shows a single
 * portfolio's breakdown behind a picker.
 */
export function usePortfolioPicker() {
  const [portfolios, setPortfolios] = useState<Portfolio[]>([]);
  const [selectedPortfolio, setSelectedPortfolio] = useState<string>("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .listPortfolios()
      .then((list) => {
        setPortfolios(list);
        setSelectedPortfolio((current) => current || list[0]?.id || "");
      })
      .catch((e) => setError(String(e.message || e)))
      .finally(() => setLoading(false));
  }, []);

  return { portfolios, selectedPortfolio, setSelectedPortfolio, loading, error };
}

/** One portfolio's current snapshot, refetched whenever the selection changes. */
export function usePortfolioSnapshot(portfolioId: string): PortfolioSnapshot | null {
  return useLatestFetch(portfolioId ? () => api.getSnapshot(portfolioId) : null, [portfolioId]);
}
