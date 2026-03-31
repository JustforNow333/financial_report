"use client";

import { useState } from "react";

import { InternationalSnapshotsTable } from "./components/InternationalSnapshotsTable";
import { MoversTable } from "./components/MoversTable";
import { useInternationalMovers } from "./hooks/useInternationalMovers";
import { useInternationalSnapshots } from "./hooks/useInternationalSnapshots";
import { useMarketMovers } from "./hooks/useMarketMovers";
import { formatEtTimestamp } from "./lib/format";

type DashboardTab = "us" | "both" | "international";

export default function HomePage() {
  const [selectedTab, setSelectedTab] = useState<DashboardTab>("us");
  const [selectedIndustry, setSelectedIndustry] = useState<string>("All");
  const topCount = selectedIndustry === "All" ? 10 : 5;
  const internationalLimit = selectedTab === "international" ? 100 : 40;

  const {
    industries,
    industriesError,
    industriesLoading,
    moversData,
    moversError,
    moversLoading,
    noSnapshotsYet,
  } = useMarketMovers(selectedIndustry, topCount);
  const {
    snapshotsData: internationalData,
    snapshotsError: internationalError,
    snapshotsLoading: internationalLoading,
    noSnapshotsYet: noInternationalSnapshotsYet,
  } = useInternationalSnapshots(internationalLimit);
  const {
    moversData: internationalMoversData,
    moversError: internationalMoversError,
    moversLoading: internationalMoversLoading,
    noMoversYet: noInternationalMoversYet,
  } = useInternationalMovers(10);
  const latestInternationalTimestamp = internationalData?.snapshots.reduce<string | null>((latest, row) => {
    if (!row.price_timestamp_utc) {
      return latest;
    }
    if (latest === null) {
      return row.price_timestamp_utc;
    }
    return row.price_timestamp_utc > latest ? row.price_timestamp_utc : latest;
  }, null);

  const moversMetaText = moversData
    ? `As of: ${moversData.asof_date ?? moversData.asof_ts.slice(0, 10)} | Industry: ${
        moversData.industry
      } | Provider: ${moversData.provider ?? "polygon_grouped_daily_bars"} | Symbols considered: ${
        moversData.total_symbols_considered ?? 0
      } | Outliers excluded: ${moversData.outliers_excluded_count ?? 0} | Last updated ET: ${formatEtTimestamp(
        moversData.asof_ts
      )}`
    : "No snapshot data yet.";
  const internationalMetaText = internationalData
    ? `As of: ${internationalData.asof_date} | Provider: ${internationalData.provider} | Companies shown: ${
        internationalData.count
      } / ${internationalData.total_available} | Latest price timestamp ET: ${
        latestInternationalTimestamp ? formatEtTimestamp(latestInternationalTimestamp) : "n/a"
      }`
    : "No international snapshot data yet.";
  const showUsSection = selectedTab === "us" || selectedTab === "both";
  const showInternationalSection = selectedTab === "international" || selectedTab === "both";

  return (
    <main className="page">
      <header className="hero">
        <h1>Market Movers Dashboard</h1>
        <p>
          {selectedTab === "us"
            ? selectedIndustry === "All"
              ? "Top U.S. gainers and losers across the latest completed market day."
              : `Top U.S. gainers and losers in ${selectedIndustry}.`
            : selectedTab === "international"
              ? "Latest known USD-normalized international company snapshot from the curated universe."
              : "Combined U.S. movers and curated international latest-known snapshots."}
        </p>
      </header>

      <section className="tabs" aria-label="Dashboard view filter">
        <button
          type="button"
          className={selectedTab === "us" ? "tab active" : "tab"}
          onClick={() => setSelectedTab("us")}
        >
          US only
        </button>
        <button
          type="button"
          className={selectedTab === "both" ? "tab active" : "tab"}
          onClick={() => setSelectedTab("both")}
        >
          Both
        </button>
        <button
          type="button"
          className={selectedTab === "international" ? "tab active" : "tab"}
          onClick={() => setSelectedTab("international")}
        >
          International
        </button>
      </section>

      {showUsSection ? (
        <>
          <section className="sectionHeader">
            <div>
              <h2>U.S. Movers</h2>
              <p>Industry filter applies only to the U.S. movers view.</p>
            </div>
            <div className="toolbar">
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
            </div>
          </section>

          {industriesError ? <div className="error">Failed to load industries.</div> : null}
          {moversError && !noSnapshotsYet ? <div className="error">Failed to load U.S. movers.</div> : null}

          <section className="meta">
            {moversLoading ? (
              <span>Loading latest U.S. movers...</span>
            ) : noSnapshotsYet ? (
              <span>No U.S. snapshot data yet. Run one U.S. ingest cycle, then refresh.</span>
            ) : (
              <span>{moversMetaText}</span>
            )}
          </section>

          <section className="grid">
            <MoversTable title={`Top ${topCount} Gainers`} rows={moversData?.gainers ?? []} />
            <MoversTable title={`Top ${topCount} Losers`} rows={moversData?.losers ?? []} />
          </section>
        </>
      ) : null}

      {showInternationalSection ? (
        <>
          <section className="sectionHeader">
            <div>
              <h2>International Snapshot</h2>
              <p>Latest known non-U.S. companies from the curated EODHD universe, normalized to USD.</p>
            </div>
          </section>

          {internationalError && !noInternationalSnapshotsYet ? (
            <div className="error">Failed to load international snapshots.</div>
          ) : null}
          {internationalMoversError && !noInternationalMoversYet ? (
            <div className="error">Failed to load international movers.</div>
          ) : null}

          <section className="meta">
            {internationalLoading ? (
              <span>Loading latest international snapshot...</span>
            ) : noInternationalSnapshotsYet ? (
              <span>No international snapshot data yet. Run one international ingest cycle, then refresh.</span>
            ) : (
              <span>{internationalMetaText}</span>
            )}
          </section>

          <section className="grid">
            <InternationalSnapshotsTable
              title="Top 10 International Winners"
              rows={internationalMoversData?.gainers ?? []}
            />
            <InternationalSnapshotsTable
              title="Top 10 International Losers"
              rows={internationalMoversData?.losers ?? []}
            />
          </section>

          <section className="meta">
            {internationalMoversLoading ? (
              <span>Loading international top 10 winners and losers...</span>
            ) : null}
          </section>

          <section className="singleColumn">
            <InternationalSnapshotsTable
              title={
                selectedTab === "international"
                  ? "Curated International Companies"
                  : "Curated International Companies Snapshot"
              }
              rows={internationalData?.snapshots ?? []}
            />
          </section>
        </>
      ) : null}
    </main>
  );
}
