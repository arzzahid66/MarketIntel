"""Market data pipeline: ingest, cache, and signal computation.

Shared by the worker (scheduled ingest) and the API (rate-limited background
revalidation), so the two can never disagree about how a quote is stored.

    provider --ingest--> latest_quotes (durable) + Redis quote:{SYMBOL} (fast)
                                   |
                                   +--> publish market:updates  --> SSE streams

Read path rules:
  * A page request never waits on a provider. It reads Redis, falls back to
    Postgres on a cache miss, and repopulates Redis. A cold cache costs one
    indexed query, not an outbound HTTP call.
  * Freshness is judged by `fetched_at` on the server clock.
"""

from __future__ import annotations

import json
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

import redis
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.core.redis import report_redis_failure
from app.models.market import LatestQuote, PriceBar, SignalSnapshot
from app.models.ticker import Ticker
from app.providers.base import MarketDataProvider, ProviderError, Quote
from app.services import signals as signal_engine
from app.services.market_hours import EXCHANGE_TZ, market_status

log = get_logger("services.market_data")

QUOTE_KEY = "quote:{symbol}"
#: Hard expiry only. Freshness is decided by fetched_at, not by the key vanishing,
#: so the last known value survives a long provider outage.
QUOTE_CACHE_TTL_SECONDS = 7 * 24 * 3600
UPDATES_CHANNEL = "market:updates"
SPARKLINE_SESSIONS = 7
#: Bars loaded for a signal: the engine's minimum plus headroom for RSI smoothing.
SIGNAL_HISTORY_SESSIONS = max(signal_engine.MIN_HISTORY, 120)


# ---------------------------------------------------------------------------
# Serialisation
# ---------------------------------------------------------------------------


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def quote_to_cache(symbol: str, row: LatestQuote) -> dict[str, Any]:
    return {
        "symbol": symbol,
        "price": row.price,
        "change": row.change,
        "change_percent": row.change_percent,
        "previous_close": row.previous_close,
        "open": row.open,
        "high": row.high,
        "low": row.low,
        "provider_time": _iso(row.provider_time),
        "fetched_at": _iso(row.fetched_at),
        "source": row.source,
    }


def session_of(instant: datetime | None) -> date | None:
    """The exchange-local trading date an instant belongs to."""
    return instant.astimezone(EXCHANGE_TZ).date() if instant else None


# ---------------------------------------------------------------------------
# Universe
# ---------------------------------------------------------------------------


def big7_tickers(db: Session) -> list[Ticker]:
    return list(
        db.scalars(
            select(Ticker)
            .where(Ticker.is_big7.is_(True), Ticker.is_active.is_(True))
            .order_by(Ticker.big7_order)
        ).all()
    )


def publish_update(client: redis.Redis | None, kind: str, now: datetime) -> None:
    if client is None:
        return
    try:
        client.publish(UPDATES_CHANNEL, json.dumps({"type": kind, "at": now.isoformat()}))
    except redis.RedisError as exc:
        report_redis_failure(exc)
        log.warning("publish_failed", kind=kind, error=str(exc))


# ---------------------------------------------------------------------------
# Ingest
# ---------------------------------------------------------------------------


@dataclass
class IngestResult:
    updated: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    failed: dict[str, str] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.failed


def _upsert_latest_quote(db: Session, ticker: Ticker, quote: Quote, now: datetime) -> None:
    values = {
        "ticker_id": ticker.id,
        "price": quote.price,
        "change": quote.change,
        "change_percent": quote.change_percent,
        "previous_close": quote.previous_close,
        "open": quote.open,
        "high": quote.high,
        "low": quote.low,
        "provider_time": quote.provider_time,
        "fetched_at": now,
        "source": quote.source,
    }
    statement = insert(LatestQuote).values(**values)
    db.execute(
        statement.on_conflict_do_update(
            index_elements=[LatestQuote.ticker_id],
            set_={k: statement.excluded[k] for k in values if k != "ticker_id"},
        )
    )


def ingest_quotes(
    db: Session,
    provider: MarketDataProvider,
    tickers: list[Ticker],
    now: datetime,
    client: redis.Redis | None,
) -> IngestResult:
    """Fetch one quote per ticker. One bad symbol never blocks the others."""
    result = IngestResult()
    for ticker in tickers:
        try:
            quote = provider.get_quote(ticker.symbol)
        except ProviderError as exc:
            result.failed[ticker.symbol] = str(exc)
            log.warning("quote_ingest_failed", symbol=ticker.symbol, error=str(exc))
            continue
        _upsert_latest_quote(db, ticker, quote, now)
        result.updated.append(ticker.symbol)
    db.commit()

    if result.updated:
        write_quotes_to_cache(db, client, [t for t in tickers if t.symbol in result.updated])
        publish_update(client, "quotes", now)
    return result


def ingest_daily_bars(
    db: Session,
    provider: MarketDataProvider,
    tickers: list[Ticker],
    now: datetime,
    backfill_sessions: int = 150,
) -> IngestResult:
    """Bring every ticker's bars up to the last completed session.

    Idempotent, so it can run on a loose schedule: it asks the provider only for
    sessions it does not already hold, and a completed bar is never rewritten.
    """
    result = IngestResult()
    target = market_status(now).last_completed_session

    # Unpacked rather than dict(...) so the key and value types are visible:
    # SQLAlchemy hands back Row objects, which dict() types as dict[Never, Never].
    latest_by_ticker: dict[uuid.UUID, date] = {  # noqa: C416
        ticker_id: last_session
        for ticker_id, last_session in db.execute(
            select(PriceBar.ticker_id, func.max(PriceBar.session_date))
            .where(PriceBar.ticker_id.in_([t.id for t in tickers]))
            .group_by(PriceBar.ticker_id)
        ).all()
    }

    for ticker in tickers:
        latest: date | None = latest_by_ticker.get(ticker.id)
        if latest is not None and latest >= target:
            result.skipped.append(ticker.symbol)
            continue
        # ~1.5 calendar days per session covers weekends and holidays.
        start = (
            latest + timedelta(days=1)
            if latest
            else target - timedelta(days=int(backfill_sessions * 1.5))
        )
        try:
            bars = provider.get_daily_bars(ticker.symbol, start, target)
        except ProviderError as exc:
            result.failed[ticker.symbol] = str(exc)
            log.warning("bars_ingest_failed", symbol=ticker.symbol, error=str(exc))
            continue

        if bars:
            db.execute(
                insert(PriceBar)
                .values(
                    [
                        {
                            "ticker_id": ticker.id,
                            "session_date": bar.session_date,
                            "open": bar.open,
                            "high": bar.high,
                            "low": bar.low,
                            "close": bar.close,
                            "volume": bar.volume,
                            "source": bar.source,
                            "fetched_at": now,
                        }
                        for bar in bars
                    ]
                )
                .on_conflict_do_nothing(constraint="uq_price_bar_session")
            )
        result.updated.append(ticker.symbol)
    db.commit()
    return result


def refresh_profiles(
    db: Session,
    provider: MarketDataProvider,
    tickers: list[Ticker],
    now: datetime,
    max_age: timedelta = timedelta(hours=20),
) -> IngestResult:
    """Nightly fundamentals: market cap and industry."""
    result = IngestResult()
    for ticker in tickers:
        if ticker.profile_updated_at and now - ticker.profile_updated_at < max_age:
            result.skipped.append(ticker.symbol)
            continue
        try:
            profile = provider.get_profile(ticker.symbol)
        except ProviderError as exc:
            result.failed[ticker.symbol] = str(exc)
            log.warning("profile_ingest_failed", symbol=ticker.symbol, error=str(exc))
            continue
        ticker.market_cap = profile.market_cap
        ticker.industry = profile.industry or ticker.industry
        ticker.exchange = profile.exchange or ticker.exchange
        ticker.profile_updated_at = now
        result.updated.append(ticker.symbol)
    db.commit()
    return result


# ---------------------------------------------------------------------------
# Signals
# ---------------------------------------------------------------------------


def recent_bars(db: Session, ticker_ids: list[Any], sessions: int) -> dict[Any, list[PriceBar]]:
    """The last `sessions` bars per ticker, oldest first, in one query."""
    if not ticker_ids:
        return {}
    ranked = (
        select(
            PriceBar.id,
            func.row_number()
            .over(partition_by=PriceBar.ticker_id, order_by=PriceBar.session_date.desc())
            .label("rank"),
        )
        .where(PriceBar.ticker_id.in_(ticker_ids))
        .subquery()
    )
    rows = db.scalars(
        select(PriceBar)
        .join(ranked, ranked.c.id == PriceBar.id)
        .where(ranked.c.rank <= sessions)
        .order_by(PriceBar.ticker_id, PriceBar.session_date)
    ).all()
    grouped: dict[Any, list[PriceBar]] = defaultdict(list)
    for bar in rows:
        grouped[bar.ticker_id].append(bar)
    return grouped


def compute_signals(
    db: Session,
    tickers: list[Ticker],
    now: datetime,
    client: redis.Redis | None,
) -> IngestResult:
    """Score every ticker and persist a snapshot.

    During the session the live price stands in for today's close in the price,
    RSI and return components. Today's volume is incomplete until the close, so
    the volume component uses the last completed session; the snapshot's inputs
    record exactly which was used.
    """
    result = IngestResult()
    status = market_status(now)
    bars_by_ticker = recent_bars(db, [t.id for t in tickers], SIGNAL_HISTORY_SESSIONS)
    # Imported here rather than at module scope: feed imports market_data for
    # nothing, but the reverse edge would still make the two modules circular.
    from app.services.feed import sentiment_for_tickers

    news = sentiment_for_tickers(db, [t.id for t in tickers], now)
    quotes = {
        q.ticker_id: q
        for q in db.scalars(
            select(LatestQuote).where(LatestQuote.ticker_id.in_([t.id for t in tickers]))
        ).all()
    }

    for ticker in tickers:
        bars = bars_by_ticker.get(ticker.id, [])
        closes = [b.close for b in bars]
        volumes = [float(b.volume) for b in bars]
        intraday = False

        quote = quotes.get(ticker.id)
        if (
            status.is_open
            and quote is not None
            and session_of(quote.provider_time) == status.current_session
            and bars
            and bars[-1].session_date < status.current_session  # type: ignore[operator]
        ):
            closes.append(quote.price)
            volumes.append(volumes[-1])
            intraday = True

        signal = (
            signal_engine.compute_signal(closes, volumes, news.get(ticker.id)) if closes else None
        )
        if signal is None:
            result.skipped.append(ticker.symbol)
            continue

        payload = signal.to_json()
        payload["inputs"]["intraday"] = intraday
        payload["inputs"]["as_of_session"] = (
            status.current_session.isoformat()
            if intraday and status.current_session
            else bars[-1].session_date.isoformat()
        )
        db.add(
            SignalSnapshot(
                ticker_id=ticker.id,
                score=signal.score,
                band=signal.band,
                formula_version=signal.formula_version,
                components_json=payload,
                source=bars[-1].source,
                computed_at=now,
            )
        )
        result.updated.append(ticker.symbol)
    db.commit()

    if result.updated:
        publish_update(client, "signals", now)
    return result


def latest_signals(db: Session, ticker_ids: list[Any]) -> dict[Any, SignalSnapshot]:
    if not ticker_ids:
        return {}
    rows = db.scalars(
        select(SignalSnapshot)
        .where(SignalSnapshot.ticker_id.in_(ticker_ids))
        .order_by(SignalSnapshot.ticker_id, SignalSnapshot.computed_at.desc())
        .distinct(SignalSnapshot.ticker_id)
    ).all()
    return {row.ticker_id: row for row in rows}


# ---------------------------------------------------------------------------
# Cache read path
# ---------------------------------------------------------------------------


def write_quotes_to_cache(db: Session, client: redis.Redis | None, tickers: list[Ticker]) -> None:
    if client is None or not tickers:
        return
    by_id = {t.id: t for t in tickers}
    rows = db.scalars(select(LatestQuote).where(LatestQuote.ticker_id.in_(by_id))).all()
    try:
        with client.pipeline(transaction=False) as pipe:
            for row in rows:
                symbol = by_id[row.ticker_id].symbol
                pipe.set(
                    QUOTE_KEY.format(symbol=symbol),
                    json.dumps(quote_to_cache(symbol, row)),
                    ex=QUOTE_CACHE_TTL_SECONDS,
                )
            pipe.execute()
    except redis.RedisError as exc:
        report_redis_failure(exc)
        log.warning("quote_cache_write_failed", error=str(exc))


@dataclass
class CachedQuotes:
    quotes: dict[str, dict[str, Any]]
    #: Symbols that were not in Redis and were served from Postgres instead.
    cache_misses: list[str]


def read_quotes(db: Session, client: redis.Redis | None, tickers: list[Ticker]) -> CachedQuotes:
    """Redis first, Postgres on a miss, then warm Redis. Never calls a provider."""
    quotes: dict[str, dict[str, Any]] = {}
    missing = list(tickers)

    if client is not None and tickers:
        try:
            raw = client.mget([QUOTE_KEY.format(symbol=t.symbol) for t in tickers])
            missing = []
            for ticker, value in zip(tickers, raw, strict=True):
                if value is None:
                    missing.append(ticker)
                else:
                    quotes[ticker.symbol] = json.loads(value)
        except (redis.RedisError, ValueError) as exc:
            if isinstance(exc, redis.RedisError):
                report_redis_failure(exc)
                # Do not try to write back to a Redis that just failed.
                client = None
            log.warning("quote_cache_read_failed", error=str(exc))
            missing = [t for t in tickers if t.symbol not in quotes]

    if missing:
        by_id = {t.id: t for t in missing}
        for row in db.scalars(select(LatestQuote).where(LatestQuote.ticker_id.in_(by_id))).all():
            symbol = by_id[row.ticker_id].symbol
            quotes[symbol] = quote_to_cache(symbol, row)
        write_quotes_to_cache(db, client, missing)

    return CachedQuotes(quotes=quotes, cache_misses=[t.symbol for t in missing])
