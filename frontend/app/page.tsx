"use client";

import { useState } from "react";

import { MoversTable } from "./components/MoversTable";
import { useMarketMovers } from "./hooks/useMarketMovers";
import { formatEtTimestamp } from "./lib/format";

export default function HomePage() {
  const [selectedIndustry, setSelectedIndustry] = useState<string>("All");
  const topCount = selectedIndustry === "All" ? 10 : 5;

  const {
    industries,
    industriesError,
    industriesLoading,
    moversData,
    moversError,
    moversLoading,
    noSnapshotsYet,
  } = useMarketMovers(selectedIndustry, topCount);

  const moversMetaText = moversData
    ? `As of: ${moversData.asof_date ?? moversData.asof_ts.slice(0, 10)} | Industry: ${
        moversData.industry
      } | Provider: ${moversData.provider ?? "polygon_grouped_daily_bars"} | Symbols considered: ${
        moversData.total_symbols_considered ?? 0
      } | Outliers excluded: ${moversData.outliers_excluded_count ?? 0} | Last updated ET: ${formatEtTimestamp(
        moversData.asof_ts
      )}`
    : "No snapshot data yet.";

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
        ) : (
          <span>{moversMetaText}</span>
        )}
      </section>

      <section className="grid">
        <MoversTable title={`Top ${topCount} Gainers`} rows={moversData?.gainers ?? []} />
        <MoversTable title={`Top ${topCount} Losers`} rows={moversData?.losers ?? []} />
      </section>
    </main>
  );
}
