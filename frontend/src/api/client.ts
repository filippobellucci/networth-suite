import type {
  Portfolio, Asset, HoldingEntry, CashAccount, CashBalanceEntry,
  PortfolioSnapshot, NetWorthHistory, DashboardSummary,
  AssetAllocationRecord, PortfolioGeoAllocation, AllocationCategory,
} from "../types";

const GATEWAY_URL = import.meta.env.VITE_GATEWAY_URL || "http://localhost:8080";

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const res = await fetch(`${GATEWAY_URL}${path}`, {
    ...options,
    headers:
      options.body && !(options.body instanceof FormData)
        ? { "Content-Type": "application/json", ...options.headers }
        : options.headers,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail || JSON.stringify(body);
    } catch {
      /* ignore */
    }
    throw new Error(detail);
  }
  if (res.status === 204) return undefined as T;
  return res.json();
}

const json = (body: unknown) => JSON.stringify(body);

export const api = {
  // ---- Portfolios
  listPortfolios: () => request<Portfolio[]>("/api/core/portfolios"),
  createPortfolio: (data: { name: string; base_currency: string; notes?: string }) =>
    request<Portfolio>("/api/core/portfolios", { method: "POST", body: json(data) }),
  updatePortfolio: (id: string, data: Partial<Pick<Portfolio, "name" | "base_currency" | "notes" | "archived">>) =>
    request<Portfolio>(`/api/core/portfolios/${id}`, { method: "PATCH", body: json(data) }),
  deletePortfolio: (id: string) => request<void>(`/api/core/portfolios/${id}`, { method: "DELETE" }),

  // ---- Assets (global catalogue)
  listAssets: (search?: string) =>
    request<Asset[]>(`/api/core/assets${search ? `?search=${encodeURIComponent(search)}` : ""}`),
  createAsset: (data: Omit<Asset, "id">) => request<Asset>("/api/core/assets", { method: "POST", body: json(data) }),
  updateAsset: (id: string, data: Partial<Omit<Asset, "id">>) =>
    request<Asset>(`/api/core/assets/${id}`, { method: "PATCH", body: json(data) }),
  deleteAsset: (id: string) => request<void>(`/api/core/assets/${id}`, { method: "DELETE" }),

  // ---- Holdings
  listHoldings: (portfolioId: string, assetId?: string) =>
    request<HoldingEntry[]>(
      `/api/core/portfolios/${portfolioId}/holdings${assetId ? `?asset_id=${assetId}` : ""}`
    ),
  addHolding: (portfolioId: string, data: { asset_id: string; entry_date: string; quantity: number; manual_price?: number | null }) =>
    request<HoldingEntry>(`/api/core/portfolios/${portfolioId}/holdings`, { method: "POST", body: json(data) }),
  updateHolding: (entryId: string, data: Partial<{ entry_date: string; quantity: number; manual_price: number | null }>) =>
    request<HoldingEntry>(`/api/core/holdings/${entryId}`, { method: "PATCH", body: json(data) }),
  deleteHolding: (entryId: string) => request<void>(`/api/core/holdings/${entryId}`, { method: "DELETE" }),

  // ---- Cash (also used for Emergency Fund / Pension Fund, distinguished by `category`)
  listCashAccounts: (portfolioId: string) =>
    request<CashAccount[]>(`/api/core/portfolios/${portfolioId}/cash-accounts`),
  createCashAccount: (
    portfolioId: string,
    data: { name: string; currency: string; institution?: string; category?: AllocationCategory }
  ) => request<CashAccount>(`/api/core/portfolios/${portfolioId}/cash-accounts`, { method: "POST", body: json(data) }),
  deleteCashAccount: (accountId: string) => request<void>(`/api/core/cash-accounts/${accountId}`, { method: "DELETE" }),
  addCashBalance: (accountId: string, data: { entry_date: string; balance: number }) =>
    request<CashBalanceEntry>(`/api/core/cash-accounts/${accountId}/balances`, { method: "POST", body: json(data) }),

  // ---- Valuation
  getSnapshot: (portfolioId: string, refresh = false) =>
    request<PortfolioSnapshot>(`/api/core/portfolios/${portfolioId}/snapshot${refresh ? "?refresh=true" : ""}`),
  getHistory: (portfolioId: string) => request<NetWorthHistory>(`/api/core/portfolios/${portfolioId}/history`),

  // ---- Dashboard (gateway aggregation)
  getDashboardSummary: (baseCurrency = "EUR") =>
    request<DashboardSummary>(`/api/dashboard/summary?base_currency=${baseCurrency}`),

  // ---- Geo allocation
  uploadAssetAllocation: (assetId: string, file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<AssetAllocationRecord>(`/api/geo/allocation/assets/${assetId}/upload`, {
      method: "POST",
      body: form,
    });
  },
  getAssetAllocation: (assetId: string) =>
    request<AssetAllocationRecord>(`/api/geo/allocation/assets/${assetId}`),
  listAssetAllocations: () => request<AssetAllocationRecord[]>(`/api/geo/allocation/assets`),
  deleteAssetAllocation: (assetId: string) =>
    request<void>(`/api/geo/allocation/assets/${assetId}`, { method: "DELETE" }),
  getPortfolioGeoAllocation: (portfolioId: string, category?: "STOCK" | "BOND", groupBy: "country" | "region" = "country") => {
    const params = new URLSearchParams({ group_by: groupBy });
    if (category) params.set("category", category);
    return request<PortfolioGeoAllocation>(`/api/dashboard/geo-allocation/${portfolioId}?${params.toString()}`);
  },

  // ---- Modules health
  getModulesHealth: () => request<{ gateway: string; modules: Record<string, string> }>("/health"),
};
