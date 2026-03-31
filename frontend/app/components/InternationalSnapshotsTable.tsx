"use client";

import { formatCurrencyValue, formatEtTimestamp, formatMoney, formatPct } from "../lib/format";
import type { InternationalSnapshotRow } from "../lib/types";

type InternationalSnapshotsTableProps = {
  title: string;
  rows: InternationalSnapshotRow[];
};

export function InternationalSnapshotsTable({
  title,
  rows,
}: InternationalSnapshotsTableProps) {
  return (
    <section className="card">
      <h2>{title}</h2>
      <div className="tableWrap">
        <table>
          <thead>
            <tr>
              <th>Ticker</th>
              <th>Company</th>
              <th>Exchange</th>
              <th>Country</th>
              <th>CCY</th>
              <th>Local</th>
              <th>USD</th>
              <th>% Growth</th>
              <th>Status</th>
              <th>Price Time</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={`${row.ticker}-${row.as_of_date}`}>
                <td className="ticker">{row.ticker}</td>
                <td className="company">{row.name ?? row.ticker}</td>
                <td>{row.exchange}</td>
                <td>{row.country}</td>
                <td>{row.currency}</td>
                <td>{formatCurrencyValue(row.local_price, row.currency)}</td>
                <td>{formatMoney(row.usd_price)}</td>
                <td className={row.pct_growth !== null && row.pct_growth >= 0 ? "gain" : "loss"}>
                  {formatPct(row.pct_growth)}
                </td>
                <td>{row.market_status ?? "-"}</td>
                <td>{row.price_timestamp_utc ? formatEtTimestamp(row.price_timestamp_utc) : "-"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
