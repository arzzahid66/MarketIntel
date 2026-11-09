/**
 * The homepage dashboard, section 6 rule 1: one aligned table, not a card grid.
 *
 * Comparison is the whole job of this screen, so the eye scans down a column.
 * Every figure is tabular-nums (set globally on td/th) and the row height is the
 * shared ROW_HEIGHT constant, so the skeleton and a loaded row are the same size.
 */

import { SignalCell } from "@/components/ui/SignalBadge";
import { ROW_HEIGHT, SkeletonTable } from "@/components/ui/Skeleton";
import { directionOf, formatPercent, formatPrice } from "@/lib/format";
import { formatSessionDay } from "@/lib/market";
import type { MarketRow } from "@/lib/types";

/** Column skeleton widths, in table order. */
export const SKELETON_COLUMNS = ["w-16", "w-20", "w-14", "w-24", "w-28"];

const DIRECTION_CLASS = {
  bull: "text-bull",
  bear: "text-bear",
  flat: "text-flat",
} as const;

export function Sparkline({ points }: { points: number[] }) {
  if (points.length < 2) {
    return <span className="text-flat">—</span>;
  }
  const min = Math.min(...points);
  const max = Math.max(...points);
  const range = max - min || 1;
  const path = points
    .map((value, index) => {
      const x = (index / (points.length - 1)) * 64;
      const y = 2 + (1 - (value - min) / range) * 14;
      return `${index === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
  const first = points[0] ?? 0;
  const last = points.at(-1) ?? 0;
  const stroke =
    last > first ? "var(--color-bull)" : last < first ? "var(--color-bear)" : "var(--color-flat)";

  return (
    <svg width="64" height="18" viewBox="0 0 64 18" aria-hidden="true" className="block">
      <path d={path} fill="none" stroke={stroke} strokeWidth="1.5" strokeLinejoin="round" />
    </svg>
  );
}

export function TickerTable({ rows, loading = false }: { rows: MarketRow[]; loading?: boolean }) {
  return (
    // Scrolls sideways on a phone; on wider screens overflow stays visible so
    // the signal breakdown can open over the rows below it.
    <div className="overflow-x-auto sm:overflow-visible">
      <table className="w-full min-w-[640px] border-collapse text-body">
        <caption className="sr-only">
          Big 7 tickers with price, daily change, seven-session trend and directional signal
        </caption>
        <thead>
          <tr className="text-small text-muted">
            <th scope="col" className="px-4 pb-2 text-left font-medium">
              Ticker
            </th>
            <th scope="col" className="px-4 pb-2 text-right font-medium">
              Price
            </th>
            <th scope="col" className="px-4 pb-2 text-right font-medium">
              Change
            </th>
            <th scope="col" className="px-4 pb-2 text-left font-medium">
              7d
            </th>
            <th scope="col" className="px-4 pb-2 text-left font-medium">
              Signal
            </th>
          </tr>
        </thead>
        <tbody>
          {loading && <SkeletonTable columns={SKELETON_COLUMNS} rows={7} />}

          {!loading &&
            rows.map((row) => {
              const direction = directionOf(row.change_percent);
              return (
                <tr key={row.symbol} className="border-t border-line" style={{ height: ROW_HEIGHT }}>
                  <td className="px-4">
                    <span className="font-mono font-medium">{row.symbol}</span>
                    <span className="ml-2 hidden text-small text-muted sm:inline">{row.name}</span>
                  </td>
                  <td
                    className={`px-4 text-right font-mono ${row.is_stale ? "text-muted" : ""}`}
                    title={
                      row.as_of_session
                        ? `${row.price_basis === "live" ? "Live" : "Close"} · ${formatSessionDay(row.as_of_session)}`
                        : undefined
                    }
                  >
                    {formatPrice(row.price, row.currency)}
                    {row.is_stale && row.as_of_session && (
                      <span className="block text-small leading-none text-muted">
                        as of {formatSessionDay(row.as_of_session)}
                      </span>
                    )}
                  </td>
                  <td
                    className={`px-4 text-right font-mono ${DIRECTION_CLASS[direction]}`}
                    title={
                      row.change !== null ? `${row.change > 0 ? "+" : ""}${row.change.toFixed(2)}` : undefined
                    }
                  >
                    {formatPercent(row.change_percent)}
                  </td>
                  <td className="px-4">
                    <Sparkline points={row.sparkline} />
                  </td>
                  <td className="px-4">
                    <SignalCell signal={row.signal} symbol={row.symbol} />
                  </td>
                </tr>
              );
            })}
        </tbody>
      </table>
    </div>
  );
}
