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

// A single tagging system used across both tradable positions (Asset.category)
// and cash-like balances (CashAccount.category), so the whole portfolio can be
// broken down by the same five buckets in the "Portfolio Allocation" view.
export type AllocationCategory = "STOCK" | "BOND" | "CASH" | "EMERGENCY_FUND" | "PENSION_FUND";

export const ALLOCATION_CATEGORY_LABELS: Record<AllocationCategory, string> = {
  STOCK: "Stock",
  BOND: "Bond",
  CASH: "Cash",
  EMERGENCY_FUND: "Emergency Fund",
  PENSION_FUND: "Pension Fund",
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
  category?: AllocationCategory | null;
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
  category?: AllocationCategory | null;
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
  category?: AllocationCategory | null;
  quantity: number;
  price?: number | null;
  price_currency: string;
  price_source: "live" | "historical" | "manual" | "unavailable";
  value_base_ccy?: number | null;
}

export interface CashPosition {
  account_id: string;
  account_name: string;
  category: AllocationCategory;
  currency: string;
  balance: number;
  value_base_ccy: number;
  as_of?: string | null;
}

export interface PortfolioSnapshot {
  portfolio_id: string;
  portfolio_name: string;
  base_currency: string;
  as_of: string;
  positions: HoldingPosition[];
  cash_positions: CashPosition[];
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

export interface GrowthPeriod {
  start_date: string;
  start_value: number;
  current_value: number;
  change: number;
  change_pct: number | null;
}

export interface GrowthStats {
  current: number;
  day: GrowthPeriod | null;
  week: GrowthPeriod | null;
  month: GrowthPeriod | null;
  year: GrowthPeriod | null;
  max: GrowthPeriod | null;
}

export interface IntradayPoint {
  time: string;
  net_worth_base_ccy: number;
}

export interface NetWorthSnapshot {
  id: string;
  snapshot_date: string;
  currency: string;
  net_worth: number;
  invested_total: number;
  cash_total: number;
  source: "manual" | "auto";
  created_at: string;
}

export interface PortfolioGeoAllocation {
  portfolio_id: string;
  category?: AllocationCategory | null;
  group_by?: "country" | "region";
  regions: AllocationRegion[];
  covered_weight_pct: number;
  missing_assets: { asset_id: string; asset_name: string }[];
}
