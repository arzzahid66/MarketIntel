"""Extended markets: sector heatmap, earnings calendar, wider universe (Phase 5).

**These routes are not behind `require_feature`, and that is deliberate.** The
plan matrix gives Free "Delayed / partial" rather than nothing, so the gate is a
*string* feature (`markets.extended_access` -> `full` | `delayed`) read per
request and passed into the service, which then builds a smaller payload. A
402 here would contradict the matrix.

Everything is a read from Redis or Postgres. Like the dashboard, no route in
this file calls a provider.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select

from app.auth.deps import CurrentEntitlements, DbSession
from app.core.clock import Clock, get_clock
from app.core.redis import get_redis
from app.models.calendar import EarningsEvent
from app.models.ticker import Ticker
from app.providers.base import SIMULATED_SOURCE
from app.schemas.extended import (
    CalendarOut,
    ConstituentOut,
    EarningsEventOut,
    HeatmapOut,
    SectorTileOut,
    UniverseOut,
    UniverseRowOut,
)
from app.services import features as F
from app.services import market_data as md
from app.services import markets as markets_service

router = APIRouter(prefix="/market", tags=["extended markets"])

ClockDep = Annotated[Clock, Depends(get_clock)]


def _access(entitlements: CurrentEntitlements) -> str:
    """`full` or `delayed`, from the plan matrix.

    Anything other than the two known values is treated as `delayed`: an
    unrecognised plan row must fail closed, not hand out the paid payload.
    """
    value = entitlements.get(F.EXTENDED_MARKETS_ACCESS)
    return (
        markets_service.ACCESS_FULL
        if value == markets_service.ACCESS_FULL
        else markets_service.ACCESS_DELAYED
    )


@router.get("/heatmap", response_model=HeatmapOut)
def get_heatmap(
    db: DbSession,
    entitlements: CurrentEntitlements,
    clock: ClockDep,
) -> HeatmapOut:
    now = clock()
    access = _access(entitlements)
    heatmap = markets_service.build_heatmap(db, get_redis(), now, access)

    return HeatmapOut(
        server_time=now,
        access=access,  # type: ignore[arg-type]
        is_simulated=heatmap.is_simulated,
        covered=heatmap.covered,
        total=heatmap.total,
        tiles=[
            SectorTileOut(
                sector=tile.sector,
                change_percent=tile.change_percent,
                market_cap=tile.market_cap,
                intensity=round(tile.intensity, 4),
                count=tile.count,
                weighted_count=tile.weighted_count,
                constituents=[
                    ConstituentOut(
                        symbol=c.symbol,
                        name=c.name,
                        market_cap=c.market_cap,
                        change_percent=c.change_percent,
                        price=c.price,
                        is_big7=c.is_big7,
                    )
                    for c in tile.constituents
                ],
            )
            for tile in heatmap.tiles
        ],
    )


@router.get("/calendar", response_model=CalendarOut)
def get_calendar(
    db: DbSession,
    entitlements: CurrentEntitlements,
    clock: ClockDep,
    symbol: Annotated[str | None, Query(max_length=16)] = None,
) -> CalendarOut:
    now = clock()
    access = _access(entitlements)
    window = markets_service.read_calendar(db, now, access, symbol=symbol)

    names = dict(
        db.execute(select(Ticker.symbol, Ticker.name).where(Ticker.is_active.is_(True)))
        .tuples()
        .all()
    )

    return CalendarOut(
        server_time=now,
        access=access,  # type: ignore[arg-type]
        since=window.since,
        until=window.until,
        full_until=window.full_until,
        events=[_event_out(event, names.get(event.symbol)) for event in window.events],
    )


def _event_out(event: EarningsEvent, name: str | None) -> EarningsEventOut:
    return EarningsEventOut(
        symbol=event.symbol,
        name=name,
        session_date=event.session_date,
        timing=event.timing,
        fiscal_quarter=event.fiscal_quarter,
        fiscal_year=event.fiscal_year,
        eps_estimate=event.eps_estimate,
        eps_actual=event.eps_actual,
        revenue_estimate=event.revenue_estimate,
        revenue_actual=event.revenue_actual,
        source=event.source,
    )


@router.get("/universe", response_model=UniverseOut)
def get_universe(
    db: DbSession,
    entitlements: CurrentEntitlements,
    clock: ClockDep,
) -> UniverseOut:
    """The wider ticker list behind the heatmap.

    On a `delayed` plan this returns the Big 7 only - the same names the free
    dashboard already shows, so nothing is taken away, and the forty extra names
    are what the plan calls the "wider universe".
    """
    now = clock()
    access = _access(entitlements)
    full = access == markets_service.ACCESS_FULL

    tickers = markets_service.universe_tickers(db) if full else md.big7_tickers(db)
    cached = md.read_quotes(db, get_redis(), tickers)
    simulated = any(
        (cached.quotes.get(t.symbol) or {}).get("source") == SIMULATED_SOURCE for t in tickers
    )

    return UniverseOut(
        server_time=now,
        access=access,  # type: ignore[arg-type]
        is_simulated=simulated,
        rows=[
            UniverseRowOut(
                symbol=t.symbol,
                name=t.name,
                sector=t.sector,
                industry=t.industry,
                exchange=t.exchange,
                market_cap=float(t.market_cap) if t.market_cap else None,
                price=(cached.quotes.get(t.symbol) or {}).get("price"),
                change_percent=(cached.quotes.get(t.symbol) or {}).get("change_percent"),
                is_big7=t.is_big7,
                source=(cached.quotes.get(t.symbol) or {}).get("source"),
            )
            for t in tickers
        ],
    )
