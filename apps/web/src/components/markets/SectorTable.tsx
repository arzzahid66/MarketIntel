/**
 * The heatmap's numbers, as a table.
 *
 * The map answers "where is the weight and which way is it moving"; it cannot
 * be read precisely. Section 6 says tables are for anything comparable, so the
 * figures live here and the map stays a map. It is also the accessible path to
 * the same data - an SVG of coloured rectangles is not.
 *
 * `constituents` is empty on a `delayed` plan, so the per-name rows simply do
 * not exist rather than being hidden client-side.
 */

import { Fragment } from "react";

import { formatPercent, formatPrice } from "@/lib/format";
import type { SectorTile } from "@/lib/types";

function moveClass(value: number | null): string {
  if (value === null || value === 0) return "text-muted";
  return value > 0 ? "text-bull" : "text-bear";
}

function capLabel(marketCap: number | null): string {
  if (marketCap === null) return "—";
  if (marketCap >= 1e12) return `$${(marketCap / 1e12).toFixed(2)}T`;
  if (marketCap >= 1e9) return `$${Math.round(marketCap / 1e9)}B`;
  return `$${Math.round(marketCap / 1e6)}M`;
}

export function SectorTable({ tiles }: { tiles: SectorTile[] }) {
  const detailed = tiles.some((tile) => tile.constituents.length > 0);

  return (
    <table className="w-full border-collapse text-body">
      <thead>
        <tr className="border-b border-line text-left text-small text-muted">
          <th scope="col" className="px-4 py-2 font-medium">
            Sector
          </th>
          <th scope="col" className="px-4 py-2 text-right font-medium">
            Move
          </th>
          <th scope="col" className="px-4 py-2 text-right font-medium">
            Market cap
          </th>
          <th scope="col" className="px-4 py-2 text-right font-medium">
            Names
          </th>
        </tr>
      </thead>
      <tbody>
        {tiles.map((tile) => (
          <Fragment key={tile.sector}>
            <tr className="border-b border-line">
              <th scope="row" className="px-4 py-2 text-left font-medium">
                {tile.sector}
              </th>
              <td className={`px-4 py-2 text-right ${moveClass(tile.change_percent)}`}>
                {tile.change_percent === null ? "n/a" : formatPercent(tile.change_percent)}
              </td>
              <td className="px-4 py-2 text-right">{capLabel(tile.market_cap)}</td>
              <td className="px-4 py-2 text-right text-muted">
                {/* Weighted vs total: a tile averaged over 2 of 9 names is one
                    to distrust, so the ratio is on the page, not just in the API. */}
                {tile.weighted_count === tile.count
                  ? tile.count
                  : `${tile.weighted_count} of ${tile.count}`}
              </td>
            </tr>
            {tile.constituents.map((holding) => (
              <tr key={`${tile.sector}-${holding.symbol}`} className="border-b border-line">
                <td className="px-4 py-1.5 pl-8 text-small text-muted">
                  <span className="text-ink">{holding.symbol}</span> {holding.name}
                </td>
                <td
                  className={`px-4 py-1.5 text-right text-small ${moveClass(holding.change_percent)}`}
                >
                  {holding.change_percent === null
                    ? "—"
                    : formatPercent(holding.change_percent)}
                </td>
                <td className="px-4 py-1.5 text-right text-small text-muted">
                  {capLabel(holding.market_cap)}
                </td>
                <td className="px-4 py-1.5 text-right text-small text-muted">
                  {formatPrice(holding.price)}
                </td>
              </tr>
            ))}
          </Fragment>
        ))}
      </tbody>
      {!detailed && (
        <caption className="caption-bottom px-4 py-3 text-left text-small text-muted">
          Sector totals only on your plan. Plus and Pro break each sector down
          into its constituent companies.
        </caption>
      )}
    </table>
  );
}
