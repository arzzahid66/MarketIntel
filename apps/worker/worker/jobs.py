"""Job registry.

A job is a plain callable plus an interval. Each job decides for itself whether
there is work to do - "is the market open?", "do we already have yesterday's
bars?" - so a restart, a missed run or a duplicate run is always harmless. That
is also why there are no cron-style "run at 16:15" schedules: an interval job
that checks state cannot miss the close because the worker was down at 16:15.

Every successful run writes worker:heartbeat:{job_id}, which the Phase 5
freshness alerts read.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from app.core.clock import Clock, system_clock
from app.core.config import settings
from app.core.logging import get_logger
from app.db.session import SessionLocal
from app.llm import LLMClient, get_llm_client
from app.models.market import LatestQuote, PriceBar, SignalSnapshot
from app.models.plan import Plan
from app.models.ticker import Ticker
from app.providers import MarketDataProvider, get_market_data_provider
from app.services import calendar_ingest
from app.services import feed as feed_service
from app.services import market_data as md
from app.services import markets as markets_service
from app.services.market_hours import market_status, session_bounds
from app.sources import (
    EarningsCalendarSource,
    NewsSource,
    get_calendar_source,
    get_news_source,
)
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from worker.clients import get_redis

log = get_logger("worker.jobs")

#: Redis key prefix the Phase 5 ingest-freshness alerts read.
FRESHNESS_KEY = "worker:heartbeat:{job_id}"
FRESHNESS_TTL_SECONDS = 3600
#: Grace after the closing bell before the closing print is considered final.
CLOSE_SETTLE = timedelta(minutes=2)


@dataclass(frozen=True)
class Job:
    id: str
    func: Callable[[], None]
    #: APScheduler interval trigger, in seconds.
    interval_seconds: int
    description: str


def mark_fresh(job_id: str) -> None:
    """Record that a job completed. Absence of this key is what pages someone."""
    client = get_redis()
    if client is None:
        return
    client.set(
        FRESHNESS_KEY.format(job_id=job_id),
        datetime.now(UTC).isoformat(),
        ex=FRESHNESS_TTL_SECONDS,
    )


# ---------------------------------------------------------------------------
# "Is there work?" - pure decisions, tested directly
# ---------------------------------------------------------------------------


def quotes_needed(db: Session, now: datetime, tickers: list[Ticker] | None = None) -> bool:
    """Always during the session. Once more after the close, to capture the
    closing print. Otherwise the provider has nothing new to say.

    Scoped to `tickers` - the Big 7 by default. The wider universe writes to the
    same `latest_quotes` table on a slower interval, so a check over *all* rows
    would see the universe's older `fetched_at` and conclude the Big 7 still
    need fetching, forever, every cycle after the close.
    """
    status = market_status(now)
    if status.is_open:
        return True
    close = session_bounds(status.last_completed_session)[1]
    if now < close + CLOSE_SETTLE:
        return False

    scope = md.big7_tickers(db) if tickers is None else tickers
    if not scope:
        return False
    ids = [t.id for t in scope]
    oldest = db.scalar(
        select(func.min(LatestQuote.fetched_at)).where(LatestQuote.ticker_id.in_(ids))
    )
    count = (
        db.scalar(
            select(func.count()).select_from(LatestQuote).where(LatestQuote.ticker_id.in_(ids))
        )
        or 0
    )
    return count < len(scope) or oldest is None or oldest < close + CLOSE_SETTLE


def signals_needed(db: Session, now: datetime) -> bool:
    """During the session, every run. When closed, only until a snapshot exists
    that is newer than both the close and the latest bar ingest."""
    if market_status(now).is_open:
        return True
    close = session_bounds(market_status(now).last_completed_session)[1]
    latest_bar_fetch = db.scalar(select(func.max(PriceBar.fetched_at)))
    latest_snapshot = db.scalar(select(func.max(SignalSnapshot.computed_at)))
    if latest_bar_fetch is None:
        return False
    must_be_after = max(close, latest_bar_fetch)
    return latest_snapshot is None or latest_snapshot < must_be_after


# ---------------------------------------------------------------------------
# Jobs
# ---------------------------------------------------------------------------


def _provider() -> MarketDataProvider:
    return get_market_data_provider()


def _news_source() -> NewsSource:
    return get_news_source()


def _llm() -> LLMClient:
    return get_llm_client()


def _calendar() -> EarningsCalendarSource:
    return get_calendar_source()


def make_jobs(
    provider_factory: Callable[[], MarketDataProvider] = _provider,
    clock: Clock = system_clock,
    news_source_factory: Callable[[], NewsSource] = _news_source,
    llm_factory: Callable[[], LLMClient] = _llm,
    calendar_factory: Callable[[], EarningsCalendarSource] = _calendar,
) -> tuple[Job, ...]:
    """Builds the registry. Tests pass a fake provider and a fixed clock."""

    def heartbeat() -> None:
        """Prove the scheduler runs, the database is reachable, and Redis accepts writes."""
        with SessionLocal() as db:
            plan_count = db.scalar(select(func.count()).select_from(Plan)) or 0
        mark_fresh("heartbeat")
        log.info("heartbeat", plans_visible=plan_count)

    def ingest_quotes() -> None:
        now = clock()
        with SessionLocal() as db:
            if not quotes_needed(db, now):
                mark_fresh("ingest_quotes")
                return
            provider = provider_factory()
            result = md.ingest_quotes(db, provider, md.big7_tickers(db), now, get_redis())
        mark_fresh("ingest_quotes")
        log.info(
            "quotes_ingested",
            provider=provider.name,
            updated=len(result.updated),
            failed=result.failed or None,
        )

    def ingest_universe_quotes() -> None:
        """Quotes for the wider extended-markets universe, on a slower interval.

        Separate from `ingest_quotes` so the Big 7 - the free homepage, and the
        only tickers the signal engine scores - keep their 60-second cadence
        regardless of how large the universe grows. Quoting all of it every
        minute would spend the whole free-tier minute budget on a heatmap nobody
        is watching tick by tick.
        """
        now = clock()
        with SessionLocal() as db:
            tickers = [t for t in markets_service.universe_tickers(db) if not t.is_big7]
            if not tickers or not quotes_needed(db, now, tickers):
                mark_fresh("ingest_universe_quotes")
                return
            provider = provider_factory()
            result = md.ingest_quotes(db, provider, tickers, now, get_redis())
        mark_fresh("ingest_universe_quotes")
        log.info(
            "universe_quotes_ingested",
            provider=provider.name,
            updated=len(result.updated),
            failed=result.failed or None,
        )

    def ingest_earnings() -> None:
        """The earnings calendar for the whole market, upserted by symbol and date.

        Earnings rather than macro: Finnhub's free tier returns 403 on
        /calendar/economic. See app/sources/calendar_base.py.
        """
        now = clock()
        source = calendar_factory()
        with SessionLocal() as db:
            result = calendar_ingest.ingest_earnings(db, source, now)
        mark_fresh("ingest_earnings")
        if result.fetched or result.failed:
            log.info(
                "earnings_ingested",
                source=source.name,
                fetched=result.fetched,
                written=result.written,
                followed=result.followed,
                failed=result.failed,
            )

    def ingest_daily_bars() -> None:
        now = clock()
        with SessionLocal() as db:
            provider = provider_factory()
            result = md.ingest_daily_bars(
                db, provider, md.big7_tickers(db), now, settings.bars_backfill_sessions
            )
        mark_fresh("ingest_daily_bars")
        if result.updated or result.failed:
            log.info(
                "bars_ingested",
                provider=provider.name,
                updated=len(result.updated),
                failed=result.failed or None,
            )

    def refresh_profiles() -> None:
        """Market cap and industry, for the whole universe.

        Not just the Big 7: the heatmap sizes every tile by market cap, so a
        name without one is dropped from its sector's weighting. The 20-hour
        `max_age` guard inside `refresh_profiles` means this costs one call per
        ticker per day, not one per run.
        """
        now = clock()
        with SessionLocal() as db:
            result = md.refresh_profiles(
                db, provider_factory(), markets_service.universe_tickers(db), now
            )
        mark_fresh("refresh_profiles")
        if result.updated or result.failed:
            log.info(
                "profiles_refreshed", updated=len(result.updated), failed=result.failed or None
            )

    def compute_signals() -> None:
        now = clock()
        with SessionLocal() as db:
            if not signals_needed(db, now):
                mark_fresh("compute_signals")
                return
            result = md.compute_signals(db, md.big7_tickers(db), now, get_redis())
        mark_fresh("compute_signals")
        log.info(
            "signals_computed",
            updated=len(result.updated),
            skipped_insufficient_history=result.skipped or None,
        )

    def ingest_news() -> None:
        """Fetch and deduplicate headlines. Never calls the LLM - scoring is a
        separate job, so a slow or failing model cannot stop the feed filling."""
        now = clock()
        source = news_source_factory()
        with SessionLocal() as db:
            result = feed_service.ingest_news(db, source, md.big7_tickers(db), now)
        mark_fresh("ingest_news")
        if result.seen or result.failed:
            log.info(
                "news_ingested",
                source=source.name,
                inserted=result.inserted,
                duplicates=result.duplicates,
                duplicate_rate=round(result.duplicate_rate, 3),
                linked=result.linked,
                failed=result.failed or None,
            )

    def embed_news() -> None:
        """Embed scored articles so the AI analyst can retrieve them.

        Separate from scoring because they fail independently: the chat model
        being down must not stop embeddings, and vice versa.
        """
        now = clock()
        client = llm_factory()
        with SessionLocal() as db:
            result = feed_service.embed_pending(db, client, now, settings.news_embed_batch)
        mark_fresh("embed_news")
        if result.scored or result.failed:
            log.info(
                "news_embedded",
                model=client.embedding_model,
                embedded=result.scored,
                failed=result.failed or None,
            )

    def score_news() -> None:
        """Score a batch of unscored article-company pairs.

        Batched rather than draining the queue, so one cycle's spend is bounded
        and a backlog costs latency rather than a surprise invoice.
        """
        now = clock()
        client = llm_factory()
        with SessionLocal() as db:
            result = feed_service.score_pending(db, client, now)
        mark_fresh("score_news")
        if result.scored or result.failed:
            log.info(
                "news_scored",
                model=client.model,
                scored=result.scored,
                skipped=result.skipped,
                failed=result.failed or None,
            )

    return (
        Job("heartbeat", heartbeat, 60, "Liveness probe: scheduler + database + Redis"),
        Job(
            "ingest_quotes",
            ingest_quotes,
            settings.quote_ingest_interval_seconds,
            "Quotes during market hours, plus the closing print",
        ),
        Job(
            "ingest_universe_quotes",
            ingest_universe_quotes,
            settings.universe_quote_interval_seconds,
            "Quotes for the wider extended-markets universe",
        ),
        Job(
            "ingest_earnings",
            ingest_earnings,
            settings.calendar_ingest_interval_seconds,
            "Earnings calendar (free tier has no macro calendar)",
        ),
        Job(
            "ingest_daily_bars",
            ingest_daily_bars,
            30 * 60,
            "Daily OHLCV up to the last completed session (backfills on first run)",
        ),
        Job(
            "refresh_profiles",
            refresh_profiles,
            6 * 3600,
            "Nightly fundamentals: market cap and industry, whole universe",
        ),
        Job(
            "ingest_news",
            ingest_news,
            settings.news_ingest_interval_seconds,
            "Company news, deduplicated (no LLM calls)",
        ),
        Job(
            "score_news",
            score_news,
            settings.news_score_interval_seconds,
            "LLM sentiment and category, once per article and company",
        ),
        Job(
            "embed_news",
            embed_news,
            settings.news_embed_interval_seconds,
            "Article embeddings for the AI analyst's retrieval",
        ),
        Job(
            "compute_signals",
            compute_signals,
            settings.signal_interval_seconds,
            "Deterministic signal snapshot per ticker",
        ),
    )


JOBS: tuple[Job, ...] = make_jobs()

#: Run first on start-up, in this order, so a fresh deploy has bars before it
#: tries to compute signals from them.
STARTUP_ORDER: tuple[str, ...] = (
    "ingest_daily_bars",
    # Profiles before the universe quotes: the heatmap needs market caps to
    # weight a tile, and a tile with no caps renders as unknown rather than flat.
    "refresh_profiles",
    "ingest_quotes",
    "ingest_universe_quotes",
    "ingest_earnings",
    # News before signals: the signal's news term reads what scoring has
    # written, so running it first means the first snapshot already carries it.
    "ingest_news",
    "score_news",
    "embed_news",
    "compute_signals",
)
