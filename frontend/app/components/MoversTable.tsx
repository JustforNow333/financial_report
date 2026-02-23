"use client";

import { formatMoney, formatPct, formatVolume } from "../lib/format";
import type { MoverRow } from "../lib/types";

type MoversTableProps = {
  title: string;
  rows: MoverRow[];
};

export function MoversTable({ title, rows }: MoversTableProps) {
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
