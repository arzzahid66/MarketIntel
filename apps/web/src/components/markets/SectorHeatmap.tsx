/**
 * The sector heatmap, drawn as our own SVG treemap.
 *
 * Section 6 of the build plan forbids embedding or copying Finviz's map, so the
 * geometry is `lib/treemap.ts` (the published squarified algorithm) over our own
 * quotes and our own sector labels.
 *
 * Encoding, kept to the design system's one rule about colour:
 *   - **Area** is market cap.
 *   - **Colour** is the day's market-cap-weighted move, and saturated colour
 *     means direction and nothing else.
 *   - A sector whose move cannot be computed is drawn in the flat colour and
 *     labelled "n/a". Rendering unknown as 0% would be a flat green tile that
 *     looks like a fact.
 *
 * Rendered server-side into a fixed viewBox and scaled with CSS, so there is no
 * measure-then-draw pass and no layout shift.
 */

import { formatPercent } from "@/lib/format";
import { squarify } from "@/lib/treemap";
import type { SectorTile } from "@/lib/types";

const VIEW_WIDTH = 1000;
const VIEW_HEIGHT = 460;
/** Below this a tile cannot hold its own label without overlapping. */
const LABEL_MIN_WIDTH = 72;
const LABEL_MIN_HEIGHT = 34;

function fillFor(tile: SectorTile): string {
  if (tile.change_percent === null || tile.change_percent === 0) {
    return "var(--color-flat)";
  }
  return tile.change_percent > 0 ? "var(--color-bull)" : "var(--color-bear)";
}

/** Keep a weak move visible but clearly weak. Never fully transparent, or the
 *  tile reads as missing data rather than as a small move. */
function opacityFor(tile: SectorTile): number {
  if (tile.change_percent === null) return 0.3;
  return 0.22 + tile.intensity * 0.68;
}

function capLabel(marketCap: number): string {
  if (marketCap >= 1e12) return `$${(marketCap / 1e12).toFixed(2)}T`;
  if (marketCap >= 1e9) return `$${Math.round(marketCap / 1e9)}B`;
  return `$${Math.round(marketCap / 1e6)}M`;
}

export function SectorHeatmap({ tiles }: { tiles: SectorTile[] }) {
  const rects = squarify(
    tiles.map((tile) => ({ key: tile.sector, value: tile.market_cap, tile })),
    VIEW_WIDTH,
    VIEW_HEIGHT,
  );

  if (rects.length === 0) {
    return (
      <p className="px-4 py-8 text-center text-small text-muted">
        No sector has a market cap yet, so there is nothing to size the map by.
        The nightly profile job fills them in.
      </p>
    );
  }

  return (
    <figure className="m-0 px-4 py-4">
      <svg
        viewBox={`0 0 ${VIEW_WIDTH} ${VIEW_HEIGHT}`}
        className="block h-auto w-full"
        role="img"
        aria-label="Sector performance treemap, sized by market capitalisation"
      >
        {rects.map(({ item, x, y, width, height }) => {
          const { tile } = item;
          const showLabel = width >= LABEL_MIN_WIDTH && height >= LABEL_MIN_HEIGHT;
          const move =
            tile.change_percent === null ? "n/a" : formatPercent(tile.change_percent);
          return (
            <g key={tile.sector}>
              <title>
                {`${tile.sector} — ${move}, ${capLabel(tile.market_cap)}, ` +
                  `${tile.weighted_count} of ${tile.count} names weighted`}
              </title>
              <rect
                x={x}
                y={y}
                width={width}
                height={height}
                fill={fillFor(tile)}
                fillOpacity={opacityFor(tile)}
                stroke="var(--color-surface)"
                strokeWidth={2}
              />
              {showLabel && (
                <>
                  <text
                    x={x + 10}
                    y={y + 22}
                    className="fill-ink text-[13px] font-medium"
                  >
                    {tile.sector}
                  </text>
                  <text
                    x={x + 10}
                    y={y + 40}
                    className="fill-ink text-[13px] tabular-nums opacity-80"
                  >
                    {move}
                  </text>
                </>
              )}
            </g>
          );
        })}
      </svg>
      <figcaption className="mt-3 text-small text-muted">
        Tile area is market capitalisation; colour is today&apos;s market-cap
        weighted move. Grey means the move could not be computed.
      </figcaption>
    </figure>
  );
}
