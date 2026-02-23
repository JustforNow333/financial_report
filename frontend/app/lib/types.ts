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
