"""The extended-markets surface: sector heatmap, earnings calendar, universe.

Read paths only. Like `dashboard.py`, nothing here calls a provider - pages read
Redis, fall back to Postgres, and the worker does the fetching.

**The plan gate is `markets.extended_access`**, a string feature with two
values, resolved from `plan_features` like every other limit:

  * `full` (Plus, Pro) - sector tiles with their constituents, and the whole
    forward calendar.
  * `delayed` (Free) - the sector tiles only, and a short calendar window.

Free is deliberately not an empty page. The plan matrix says "Delayed /
partial", so Free sees the shape of the market and pays for the detail. The gate
is applied while building the payload, not by hiding fields in the UI, so a
response never carries data the reader is not entitled to.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta

import redis
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.calendar import EarningsEvent
from app.models.ticker import Ticker
from app.providers.base import SIMULATED_SOURCE
from app.services import market_data as md
from app.services.sector import Constituent, SectorTile, build_tiles

#: The two values `markets.extended_access` takes. Full access adds the
#: per-name breakdown and the long calendar window.
ACCESS_FULL = "full"
ACCESS_DELAYED = "delayed"

#: How much calendar a `delayed` reader sees. Enough to be useful - this week's
#: results - and short enough that the forward calendar is worth upgrading for.
DELAYED_CALENDAR_DAYS = 7


def universe_tickers(db: Session) -> list[Ticker]:
    """Every active name, Big 7 first. The heatmap's input."""
    return list(
        db.scalars(
            select(Ticker)
            .where(Ticker.is_active.is_(True))
            .order_by(Ticker.is_big7.desc(), Ticker.big7_order, Ticker.symbol)
        ).all()
    )


@dataclass(frozen=True)
class Heatmap:
    tiles: list[SectorTile]
    #: True when any rendered row came from the simulator. Judged on the rows,
    #: not on the configured provider - a real key does not make yesterday's
    #: simulated quote real (see `dashboard.py`).
    is_simulated: bool
    #: Names with a sector and a quote, and the total we tried to render. A
    #: heatmap built from 7 of 47 names is one to distrust out loud.
    covered: int
    total: int
    access: str


def build_heatmap(
    db: Session,
    client: redis.Redis | None,
    now: datetime,
    access: str,
) -> Heatmap:
    """Group the universe by sector and weight each tile by market cap."""
    tickers = universe_tickers(db)
    cached = md.read_quotes(db, client, tickers)

    by_sector: dict[str | None, list[Constituent]] = defaultdict(list)
    simulated = False
    covered = 0

    for ticker in tickers:
        quote = cached.quotes.get(ticker.symbol) or {}
        price = quote.get("price")
        change_percent = quote.get("change_percent")
        if quote.get("source") == SIMULATED_SOURCE:
            simulated = True
        if price is not None:
            covered += 1
        by_sector[ticker.sector].append(
            Constituent(
                symbol=ticker.symbol,
                name=ticker.name,
                market_cap=float(ticker.market_cap) if ticker.market_cap else None,
                change_percent=change_percent,
                price=price,
                is_big7=ticker.is_big7,
            )
        )

    return Heatmap(
        tiles=build_tiles(dict(by_sector), include_constituents=access == ACCESS_FULL),
        is_simulated=simulated,
        covered=covered,
        total=len(tickers),
        access=access,
    )


@dataclass(frozen=True)
class CalendarWindow:
    events: list[EarningsEvent]
    since: date
    until: date
    access: str
    #: The window a `full` reader would have got. Shown to a Free reader so the
    #: upgrade prompt can say what is actually behind it rather than guessing.
    full_until: date


def calendar_window(now: datetime, access: str) -> tuple[date, date, date]:
    """`(since, until, full_until)` for this reader, from the server clock."""
    today = now.date()
    since = today - timedelta(days=settings.calendar_lookback_days)
    full_until = today + timedelta(days=settings.calendar_horizon_days)
    until = full_until if access == ACCESS_FULL else today + timedelta(days=DELAYED_CALENDAR_DAYS)
    return since, until, full_until


def read_calendar(
    db: Session,
    now: datetime,
    access: str,
    symbol: str | None = None,
    followed_only: bool = True,
) -> CalendarWindow:
    """Scheduled and just-reported results, soonest first.

    `followed_only` keeps the panel to names in our own universe. The provider
    returns the whole market - 1,500 rows for a fortnight - and a calendar of
    companies we carry no price for is noise, not a feature.
    """
    since, until, full_until = calendar_window(now, access)

    statement = (
        select(EarningsEvent)
        .where(EarningsEvent.session_date >= since, EarningsEvent.session_date <= until)
        .order_by(EarningsEvent.session_date, EarningsEvent.symbol)
    )
    if followed_only:
        statement = statement.where(EarningsEvent.ticker_id.is_not(None))
    if symbol:
        statement = statement.where(EarningsEvent.symbol == symbol.upper())

    return CalendarWindow(
        events=list(db.scalars(statement).all()),
        since=since,
        until=until,
        access=access,
        full_until=full_until,
    )
