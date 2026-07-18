export type AssetClass =
  | "ETF"
  | "STOCK"
  | "BOND"
  | "CRYPTO"
  | "CASH"
  | "REAL_ESTATE"
  | "PENSION_FUND"
  | "OTHER";

export const ASSET_CLASS_LABELS: Record<AssetClass, string> = {
  ETF: "ETF",
  STOCK: "Stock",
  BOND: "Bond",
  CRYPTO: "Crypto",
  CASH: "Cash",
  REAL_ESTATE: "Real Estate",
  PENSION_FUND: "Pension Fund",
  OTHER: "Other",
};

export interface Portfolio {
  id: string;
  name: string;
  base_currency: string;
  notes?: string | null;
  archived: boolean;
  created_at: string;
}

export interface Asset {
  id: string;
  ticker?: string | null;
  isin?: string | null;
  name: string;
  asset_class: AssetClass;
  currency: string;
  notes?: string | null;
}

export interface HoldingEntry {
  id: string;
  portfolio_id: string;
  asset_id: string;
  entry_date: string;
  quantity: number;
  manual_price?: number | null;
}

export interface CashAccount {
  id: string;
  portfolio_id: string;
  name: string;
  currency: string;
  institution?: string | null;
}

export interface CashBalanceEntry {
  id: string;
  account_id: string;
  entry_date: string;
  balance: number;
}

export interface HoldingPosition {
  asset_id: string;
  asset_name: string;
  ticker?: string | null;
  asset_class: AssetClass;
  quantity: number;
  price?: number | null;
  price_currency: string;
  price_source: "live" | "manual" | "unavailable";
  value_base_ccy?: number | null;
}

export interface PortfolioSnapshot {
  portfolio_id: string;
  portfolio_name: string;
  base_currency: string;
  as_of: string;
  positions: HoldingPosition[];
  cash_total_base_ccy: number;
  invested_total_base_ccy: number;
  net_worth_base_ccy: number;
}

export interface NetWorthPoint {
  date: string;
  net_worth_base_ccy: number;
}

export interface NetWorthHistory {
  portfolio_id?: string | null;
  base_currency: string;
  points: NetWorthPoint[];
}

export interface DashboardSummary {
  portfolios: Portfolio[];
  snapshots: PortfolioSnapshot[];
  combined_history: NetWorthHistory | null;
}

export interface AllocationRegion {
  country: string;
  country_name: string;
  weight_pct: number;
}

export interface AssetAllocationRecord {
  asset_id: string;
  original_filename: string;
  uploaded_at: string;
  result: {
    metadata: {
      fund_name?: string | null;
      isin?: string | null;
      as_of_date?: string | null;
      source_provider?: string | null;
      parser_name?: string | null;
    };
    weights: Record<string, number>;
    unmapped_labels: Record<string, number>;
    total_weight: number;
  };
}

export interface PortfolioGeoAllocation {
  portfolio_id: string;
  regions: AllocationRegion[];
  covered_weight_pct: number;
  missing_assets: { asset_id: string; asset_name: string }[];
}

export interface PensionProjectionPoint {
  year: number;
  balance: number;
}
