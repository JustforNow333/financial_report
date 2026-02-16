"use client";

import { useMemo, useState } from "react";
import useSWR from "swr";

type MoverRow = {
  rank: number;
  ticker: string;
  name: string | null;
  last_price: number | null;
  prev_close: number | null;
  pct_change: number | null;
  volume: number | null;
};

type MoversResponse = {
  asof_date?: string;
  asof_ts: string;
  industry: string;
  provider?: string;
  total_symbols_considered?: number;
  outliers_excluded_count?: number;
  gainers: MoverRow[];
  losers: MoverRow[];
};

type IndustriesResponse = {
  industries: string[];
};

class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

const fetcher = async <T,>(path: string): Promise<T> => {
  const response = await fetch(`${API_BASE}${path}`);
  if (!response.ok) {
    const body = await response.text();
    throw new ApiError(response.status, body || `Request failed: ${response.status}`);
  }
  return (await response.json()) as T;
};

const formatMoney = (value: number | null): string => {
  if (value === null || Number.isNaN(value)) {
    return "-";
  }
  return `$${value.toFixed(2)}`;
};

const formatPct = (value: number | null): string => {
  if (value === null || Number.isNaN(value)) {
    return "-";
  }
  return `${value >= 0 ? "+" : ""}${value.toFixed(2)}%`;
};

const formatVolume = (value: number | null): string => {
  if (value === null) {
    return "-";
  }
  return new Intl.NumberFormat("en-US").format(value);
};

const formatEtTimestamp = (iso: string): string => {
  const date = new Date(iso);
  return new Intl.DateTimeFormat("en-US", {
    year: "numeric",
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: true,
    timeZone: "America/New_York",
  }).format(date);
};

function MoversTable({ title, rows }: { title: string; rows: MoverRow[] }) {
  return (
    <section className="card">
      <h2>{title}</h2>
      <div className="tableWrap">
        <table>
          <thead>
            <tr>
              <th>Rank</th>
              <th>Ticker</th>
              <th>Company</th>
              <th>Last</th>
              <th>% Change</th>
              <th>Volume</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={`${title}-${row.ticker}-${row.rank}`}>
                <td>{row.rank}</td>
                <td className="ticker">{row.ticker}</td>
                <td className="company">{row.name ?? row.ticker}</td>
                <td>{formatMoney(row.last_price)}</td>
                <td className={row.pct_change !== null && row.pct_change >= 0 ? "gain" : "loss"}>
                  {formatPct(row.pct_change)}
                </td>
                <td>{formatVolume(row.volume)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

export default function HomePage() {
  const [selectedIndustry, setSelectedIndustry] = useState<string>("All");
  const topCount = selectedIndustry === "All" ? 10 : 5;

  const { data: industriesData, error: industriesError, isLoading: industriesLoading } = useSWR<
    IndustriesResponse
  >("/api/industries", fetcher, {
    revalidateOnFocus: false,
  });

  const moversPath = useMemo(() => {
    const params = new URLSearchParams({ limit: String(topCount) });
    if (selectedIndustry !== "All") {
      params.set("industry", selectedIndustry);
    }
    return `/api/movers/latest?${params.toString()}`;
  }, [selectedIndustry, topCount]);

  const { data: moversData, error: moversError, isLoading: moversLoading } = useSWR<MoversResponse>(
    moversPath,
    fetcher,
    {
      refreshInterval: 60_000,
      revalidateOnFocus: false,
      shouldRetryOnError: false,
    }
  );

  const industries = industriesData?.industries ?? ["All"];
  const noSnapshotsYet = moversError instanceof ApiError && moversError.status === 404;

  return (
    <main className="page">
      <header className="hero">
        <h1>US Market Movers</h1>
        <p>
          {selectedIndustry === "All"
            ? "Top 10 gainers and losers across the U.S. market."
            : `Top 5 gainers and losers in ${selectedIndustry}.`}
        </p>
      </header>

      <section className="toolbar">
        <label htmlFor="industry">Industry</label>
        <select
          id="industry"
          value={selectedIndustry}
          onChange={(event) => setSelectedIndustry(event.target.value)}
          disabled={industriesLoading}
        >
          {industries.map((industry) => (
            <option key={industry} value={industry}>
              {industry}
            </option>
          ))}
        </select>
      </section>

      {industriesError ? <div className="error">Failed to load industries.</div> : null}
      {moversError && !noSnapshotsYet ? <div className="error">Failed to load movers.</div> : null}

      <section className="meta">
        {moversLoading ? (
          <span>Loading latest movers...</span>
        ) : noSnapshotsYet ? (
          <span>No snapshot data yet. Run one ingest cycle, then refresh.</span>
        ) : moversData ? (
          <span>
            As of: {moversData.asof_date ?? moversData.asof_ts.slice(0, 10)} | Industry:{" "}
            {moversData.industry} | Provider: {moversData.provider ?? "polygon_grouped_daily_bars"} |
            Symbols considered: {moversData.total_symbols_considered ?? 0} | Outliers excluded:{" "}
            {moversData.outliers_excluded_count ?? 0} | Last updated ET:{" "}
            {formatEtTimestamp(moversData.asof_ts)}
          </span>
        ) : (
          <span>No snapshot data yet.</span>
        )}
      </section>

      <section className="grid">
        <MoversTable title={`Top ${topCount} Gainers`} rows={moversData?.gainers ?? []} />
        <MoversTable title={`Top ${topCount} Losers`} rows={moversData?.losers ?? []} />
      </section>
    </main>
  );
}
