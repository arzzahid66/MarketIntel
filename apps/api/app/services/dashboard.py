"""Assembles the homepage dashboard from cache and database. Never calls a provider.

Two decisions live here and nowhere else:

  * What price to show. While the market is open, the current session's live
    quote. While it is closed, the last completed session's close - never a
    stale "live" number (Phase 2 requirement).

  * Whether it is stale. Judged on `fetched_at` by the server clock. A stale
    dashboard still renders its last-known values; it just says so, and the
    route kicks off a rate-limited background revalidation.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

import redis
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.market import PriceBar, SignalSnapshot
from app.models.ticker import Ticker
from app.providers.base import SIMULATED_SOURCE, MarketDataProvider
from app.schemas.market import (
    DashboardOut,
    MarketRowOut,
    MarketStatusOut,
    SignalComponentOut,
    SignalOut,
)
from app.services import market_data as md
from app.services import signals as signal_engine
from app.services.market_hours import MarketStatus, market_status

#: A quote older than three ingest cycles during the session is stale.
STALE_QUOTE_AFTER = timedelta(seconds=settings.quote_ingest_interval_seconds * 3)
STALE_SIGNAL_AFTER = timedelta(seconds=settings.signal_interval_seconds * 3)


@dataclass
class DashboardResult:
    dashboard: DashboardOut
    #: The route should start a background quote fetch.
    needs_revalidation: bool


def _parse_dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _change(price: float | None, previous: float | None) -> tuple[float | None, float | None]:
    if price is None or not previous:
        return None, None
    change = round(price - previous, 4)
    return change, round(change / previous * 100.0, 4)


def _signal_out(
    snapshot: SignalSnapshot | None, now: datetime, status: MarketStatus
) -> SignalOut | None:
    if snapshot is None:
        return None
    payload: dict[str, Any] = snapshot.components_json or {}
    inputs = payload.get("inputs", {})
    components: dict[str, dict[str, Any]] = payload.get("components") or {}
    # JSONB does not keep key order; present components in formula order.
    order = {key: index for index, key in enumerate(signal_engine.WEIGHTS)}
    return SignalOut(
        score=snapshot.score,
        band=snapshot.band,
        computed_at=snapshot.computed_at,
        formula_version=snapshot.formula_version,
        components=[
            SignalComponentOut(key=key, **components[key])
            for key in sorted(components, key=lambda k: order.get(k, len(order)))
        ],
        notes=list(payload.get("notes") or []),
        intraday=bool(inputs.get("intraday", False)),
        as_of_session=inputs.get("as_of_session"),
        is_stale=status.is_open and now - snapshot.computed_at > STALE_SIGNAL_AFTER,
        source=snapshot.source,
    )


def _row(
    ticker: Ticker,
    quote: dict[str, Any] | None,
    bars: list[PriceBar],
    signal: SignalSnapshot | None,
    status: MarketStatus,
    now: datetime,
) -> tuple[MarketRowOut, datetime | None]:
    bars_by_date = {bar.session_date: bar for bar in bars}
    quote_time = _parse_dt(quote.get("provider_time")) if quote else None
    quote_fetched = _parse_dt(quote.get("fetched_at")) if quote else None
    quote_session = md.session_of(quote_time or quote_fetched)

    price = previous = change = change_percent = None
    basis = "none"
    as_of: date | None = None
    fetched_at: datetime | None = None
    source: str | None = None
    stale = True
    sparkline = [bar.close for bar in bars[-md.SPARKLINE_SESSIONS :]]

    if status.is_open and quote and quote_session == status.current_session:
        price = quote["price"]
        previous = quote.get("previous_close")
        change, change_percent = quote.get("change"), quote.get("change_percent")
        if change is None or change_percent is None:
            change, change_percent = _change(price, previous)
        basis, as_of, fetched_at, source = (
            "live",
            status.current_session,
            quote_fetched,
            quote["source"],
        )
        stale = quote_fetched is None or now - quote_fetched > STALE_QUOTE_AFTER
        sparkline = [*sparkline[-(md.SPARKLINE_SESSIONS - 1) :], price]
    else:
        # The last completed session's close: the daily bar is authoritative, a
        # quote taken after that session's close is the same number.
        target = status.last_completed_session
        bar = bars_by_date.get(target)
        if bar is not None:
            earlier = [b for b in bars if b.session_date < target]
            price, as_of, fetched_at, source = bar.close, target, bar.fetched_at, bar.source
            previous = earlier[-1].close if earlier else None
            change, change_percent = _change(price, previous)
            stale = False
        elif quote and quote_session == target:
            price, previous = quote["price"], quote.get("previous_close")
            change, change_percent = _change(price, previous)
            as_of, fetched_at, source = target, quote_fetched, quote["source"]
            stale = False
        elif quote or bars:
            # Something older than the last session. Show it, flag it.
            use_quote = quote is not None and (
                not bars or (quote_session or date.min) >= bars[-1].session_date
            )
            if use_quote and quote:
                price, previous = quote["price"], quote.get("previous_close")
                as_of, fetched_at, source = quote_session, quote_fetched, quote["source"]
            else:
                last = bars[-1]
                price, as_of, fetched_at, source = (
                    last.close,
                    last.session_date,
                    last.fetched_at,
                    last.source,
                )
                previous = bars[-2].close if len(bars) > 1 else None
            change, change_percent = _change(price, previous)
        if price is not None:
            basis = "close"

    row = MarketRowOut(
        symbol=ticker.symbol,
        name=ticker.name,
        currency=ticker.currency,
        price=price,
        change=change,
        change_percent=change_percent,
        previous_close=previous,
        price_basis=basis,  # type: ignore[arg-type]
        as_of_session=as_of,
        provider_time=quote_time if basis == "live" else None,
        fetched_at=fetched_at,
        is_stale=stale,
        sparkline=[round(p, 4) for p in sparkline],
        signal=_signal_out(signal, now, status),
        source=source,
    )
    return row, fetched_at


def build_dashboard(
    db: Session,
    client: redis.Redis | None,
    tickers: list[Ticker],
    now: datetime,
    refresh_interval_seconds: int,
    provider: MarketDataProvider,
) -> DashboardResult:
    status = market_status(now)
    ids = [t.id for t in tickers]
    cached = md.read_quotes(db, client, tickers)
    # One more bar than the sparkline, so a closed-market row has its prior close.
    bars = md.recent_bars(db, ids, md.SPARKLINE_SESSIONS + 1)
    signals = md.latest_signals(db, ids)

    rows: list[MarketRowOut] = []
    fetched: list[datetime] = []
    for ticker in tickers:
        row, fetched_at = _row(
            ticker,
            cached.quotes.get(ticker.symbol),
            bars.get(ticker.id, []),
            signals.get(ticker.id),
            status,
            now,
        )
        rows.append(row)
        if fetched_at is not None:
            fetched.append(fetched_at)

    priced = [r for r in rows if r.price is not None]
    if not priced:
        data_status = "unavailable"
    elif any(r.is_stale for r in rows):
        data_status = "stale"
    else:
        data_status = "live" if status.is_open else "closed"

    # Judged on what is on screen, not on which provider is configured. Adding a
    # real key does not retroactively make yesterday's simulated bars real, and
    # the signal is computed from those bars, so a row can be simulated while the
    # provider is not. Either way the viewer must be told (build plan, Phase 2).
    is_simulated = provider.is_simulated or any(
        row.source == SIMULATED_SOURCE
        or (row.signal is not None and row.signal.source == SIMULATED_SOURCE)
        for row in rows
    )

    dashboard = DashboardOut(
        server_time=now,
        last_updated_at=max(fetched) if fetched else None,
        market=MarketStatusOut(
            is_open=status.is_open,
            session=status.session,
            reason=status.reason,
            last_completed_session=status.last_completed_session,
            next_open=status.next_open,
            next_close=status.next_close,
        ),
        data_status=data_status,  # type: ignore[arg-type]
        is_simulated=is_simulated,
        provider=provider.name,
        refresh_interval_seconds=refresh_interval_seconds,
        rows=rows,
    )
    # Worth an outbound call only if a fetch could actually change the answer.
    needs_revalidation = any(r.is_stale for r in rows)
    return DashboardResult(dashboard=dashboard, needs_revalidation=needs_revalidation)
