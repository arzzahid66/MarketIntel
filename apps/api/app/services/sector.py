"""Sector aggregation for the heatmap. Pure maths, no I/O.

**We build our own map.** The build plan is explicit that Finviz's treemap is
their intellectual property and must not be embedded or copied, so the heatmap
is computed here from our own quotes and our own sector labels, and drawn by our
own SVG component.

Two decisions worth stating, because a heatmap that aggregates badly is
confidently wrong rather than obviously broken:

  * **A sector's move is market-cap weighted**, not a plain mean. An equal-weight
    average lets the smallest company in a sector swing the tile as hard as the
    largest, which is not what "Technology is down today" means to a reader.
  * **A constituent with no market cap is dropped from the weighting but still
    listed.** Weighting by a cap we do not have would mean inventing one; hiding
    the row would mean a tile whose constituents do not add up to it.

Tile *area* is market cap and tile *colour* is the day's move - the two
dimensions the plan asks for. Both come from `SectorTile`, so the component does
no arithmetic of its own.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Moves at or beyond this percentage saturate the colour scale. Past roughly
#: 3% a day everything reads as "very red" anyway, and a scale stretched to fit
#: one outlier makes an ordinary day look flat.
COLOUR_CLAMP_PERCENT = 3.0


@dataclass(frozen=True)
class Constituent:
    symbol: str
    name: str
    #: None when the nightly profile job has not filled it in yet.
    market_cap: float | None
    change_percent: float | None
    price: float | None
    is_big7: bool


@dataclass(frozen=True)
class SectorTile:
    sector: str
    #: Market-cap weighted percentage change, or None when nothing in the sector
    #: has both a cap and a move.
    change_percent: float | None
    #: Summed market cap of the constituents that had one. The treemap's area.
    market_cap: float
    #: How many names the tile is built from, and how many of those carried a
    #: cap. A tile weighted on 2 of 9 names is a tile to distrust, so the number
    #: travels with it rather than being quietly dropped.
    count: int
    weighted_count: int
    constituents: tuple[Constituent, ...]

    @property
    def intensity(self) -> float:
        """0.0 to 1.0, how saturated the tile should be. Direction is the sign."""
        if self.change_percent is None:
            return 0.0
        return min(abs(self.change_percent), COLOUR_CLAMP_PERCENT) / COLOUR_CLAMP_PERCENT


def weighted_change(constituents: list[Constituent]) -> tuple[float | None, float, int]:
    """Market-cap weighted change, total weighted cap, and how many names counted.

    Returns `(None, cap, 0)` when no constituent has both a cap and a move: an
    average of nothing is not 0%, and a tile that renders flat when it means
    "unknown" is a lie the reader cannot see.
    """
    total_cap = 0.0
    weighted_sum = 0.0
    counted = 0
    for item in constituents:
        if item.market_cap is None or item.change_percent is None or item.market_cap <= 0:
            continue
        total_cap += item.market_cap
        weighted_sum += item.market_cap * item.change_percent
        counted += 1

    if counted == 0 or total_cap <= 0:
        return None, total_cap, 0
    return weighted_sum / total_cap, total_cap, counted


UNCLASSIFIED = "Unclassified"


def build_tiles(
    by_sector: dict[str | None, list[Constituent]],
    *,
    include_constituents: bool = True,
) -> list[SectorTile]:
    """Aggregate each sector into a tile. Largest sector by cap first.

    The sector label is `tickers.sector`, filled by the nightly profile job.
    Names with no sector yet are grouped under `UNCLASSIFIED` rather than
    dropped: an unclassified holding is a data gap to fix, and hiding it makes
    the gap invisible.

    `include_constituents` is the plan gate. A Free reader gets the tiles with
    an empty constituent list - the sector picture, without the per-name
    breakdown that is part of what Plus is for. It is a parameter here rather
    than a filter applied afterwards so the payload never carries data the
    reader is not entitled to see.
    """
    tiles: list[SectorTile] = []
    for raw_sector, members in by_sector.items():
        if not members:
            continue
        sector = (raw_sector or "").strip() or UNCLASSIFIED
        change, cap, counted = weighted_change(members)
        tiles.append(
            SectorTile(
                sector=sector,
                change_percent=round(change, 4) if change is not None else None,
                market_cap=cap,
                count=len(members),
                weighted_count=counted,
                constituents=tuple(
                    sorted(
                        members,
                        key=lambda c: (-(c.market_cap or 0.0), c.symbol),
                    )
                )
                if include_constituents
                else (),
            )
        )

    # Largest first, so the treemap lays out big tiles before small ones and
    # the eye lands on what actually moves the market.
    return sorted(tiles, key=lambda t: (-t.market_cap, t.sector))
