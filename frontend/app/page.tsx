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
  asof_ts: string;
  industry: string;
  gainers: MoverRow[];
  losers: MoverRow[];
};

type IndustriesResponse = {
  industries: string[];
};

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

const fetcher = async <T,>(path: string): Promise<T> => {
  const response = await fetch(`${API_BASE}${path}`);
  if (!response.ok) {
    const body = await response.text();
    throw new Error(body || `Request failed: ${response.status}`);
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
    dateStyle: "medium",
    timeStyle: "medium",
    timeZone: "America/New_York",
    timeZoneName: "short",
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
                <td>{row.name ?? "-"}</td>
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

  const { data: industriesData, error: industriesError, isLoading: industriesLoading } = useSWR<
    IndustriesResponse
  >("/api/industries", fetcher, {
    revalidateOnFocus: false,
  });

  const moversPath = useMemo(() => {
    if (selectedIndustry === "All") {
      return "/api/movers/latest";
    }
    return `/api/movers/latest?industry=${encodeURIComponent(selectedIndustry)}`;
  }, [selectedIndustry]);

  const { data: moversData, error: moversError, isLoading: moversLoading } = useSWR<MoversResponse>(
    moversPath,
    fetcher,
    {
      refreshInterval: 60_000,
      revalidateOnFocus: false,
    }
  );

  const industries = industriesData?.industries ?? ["All"];

  return (
    <main className="page">
      <header className="hero">
        <h1>US Market Movers</h1>
        <p>Top 10 gainers and losers from the latest full-market snapshot.</p>
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
      {moversError ? <div className="error">Failed to load movers.</div> : null}

      <section className="meta">
        {moversLoading ? (
          <span>Loading latest movers...</span>
        ) : moversData ? (
          <span>
            Last updated: {formatEtTimestamp(moversData.asof_ts)} | Industry: {moversData.industry}
          </span>
        ) : (
          <span>No snapshot data yet.</span>
        )}
      </section>

      <section className="grid">
        <MoversTable title="Top Gainers" rows={moversData?.gainers ?? []} />
        <MoversTable title="Top Losers" rows={moversData?.losers ?? []} />
      </section>
    </main>
  );
}
