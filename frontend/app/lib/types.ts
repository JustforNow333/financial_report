export type MoverRow = {
  rank: number;
  ticker: string;
  name: string | null;
  last_price: number | null;
  pct_change: number | null;
  volume: number | null;
};

export type MoversResponse = {
  asof_date?: string;
  asof_ts: string;
  industry: string;
  provider?: string;
  total_symbols_considered?: number;
  outliers_excluded_count?: number;
  gainers: MoverRow[];
  losers: MoverRow[];
};

export type IndustriesResponse = {
  industries: string[];
};

export type InternationalSnapshotRow = {
  ticker: string;
  name: string | null;
  exchange: string;
  country: string;
  currency: string;
  local_price: number | null;
  usd_price: number | null;
  prev_close: number | null;
  pct_growth: number | null;
  market_cap: number | null;
  as_of_date: string;
  provider: string;
  price_timestamp_utc: string | null;
  fx_timestamp_utc: string | null;
  market_status: string | null;
};

export type InternationalSnapshotsResponse = {
  asof_date: string;
  provider: string;
  count: number;
  total_available: number;
  country: string | null;
  exchange: string | null;
  snapshots: InternationalSnapshotRow[];
};

export type InternationalMoversResponse = {
  asof_date: string;
  provider: string;
  country: string | null;
  exchange: string | null;
  gainers: InternationalSnapshotRow[];
  losers: InternationalSnapshotRow[];
};
