"""Ingest, cache and signal pipeline, against real Postgres and Redis."""

from __future__ import annotations

import json
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.clock import fixed_clock
from app.core.redis import get_redis
from app.models.market import LatestQuote, PriceBar, SignalSnapshot
from app.providers.fake import FakeProvider
from app.services import market_data as md
from app.services.signals import MIN_HISTORY
from tests.market_helpers import FRIDAY, MONDAY_NOON_ET, SATURDAY_NOON_ET, SpyProvider, populate


def test_quote_ingest_writes_postgres_and_redis_and_announces_it(db: Session) -> None:
    client = get_redis()
    assert client is not None
    pubsub = client.pubsub(ignore_subscribe_messages=True)
    pubsub.subscribe(md.UPDATES_CHANNEL)
    pubsub.get_message(timeout=1)  # drain the subscribe confirmation

    tickers = md.big7_tickers(db)
    result = md.ingest_quotes(
        db, FakeProvider(fixed_clock(MONDAY_NOON_ET)), tickers, MONDAY_NOON_ET, client
    )

    assert sorted(result.updated) == sorted(t.symbol for t in tickers)
    assert db.scalar(select(func.count()).select_from(LatestQuote)) == 7
    cached = json.loads(client.get("quote:AAPL"))
    assert cached["source"] == "simulated"
    assert cached["fetched_at"] == MONDAY_NOON_ET.isoformat()

    message = pubsub.get_message(timeout=2)
    assert message is not None and json.loads(message["data"])["type"] == "quotes"
    pubsub.close()


def test_one_failing_symbol_does_not_block_the_rest(db: Session) -> None:
    provider = SpyProvider(MONDAY_NOON_ET, fail_symbols={"NVDA"})
    result = md.ingest_quotes(db, provider, md.big7_tickers(db), MONDAY_NOON_ET, get_redis())
    assert list(result.failed) == ["NVDA"]
    assert len(result.updated) == 6


def test_quote_ingest_overwrites_rather_than_duplicates(db: Session) -> None:
    tickers = md.big7_tickers(db)
    for minutes in (0, 5):
        now = MONDAY_NOON_ET + timedelta(minutes=minutes)
        md.ingest_quotes(db, FakeProvider(fixed_clock(now)), tickers, now, None)
    assert db.scalar(select(func.count()).select_from(LatestQuote)) == 7
    assert db.scalar(select(func.min(LatestQuote.fetched_at))) == MONDAY_NOON_ET + timedelta(
        minutes=5
    )


def test_bar_backfill_is_complete_then_idempotent(db: Session) -> None:
    tickers = md.big7_tickers(db)
    provider = SpyProvider(MONDAY_NOON_ET)

    first = md.ingest_daily_bars(db, provider, tickers, MONDAY_NOON_ET, backfill_sessions=150)
    count = db.scalar(select(func.count()).select_from(PriceBar)) or 0
    assert len(first.updated) == 7
    assert count >= 7 * MIN_HISTORY
    assert db.scalar(select(func.max(PriceBar.session_date))) == FRIDAY

    calls_before = len(provider.calls)
    second = md.ingest_daily_bars(db, provider, tickers, MONDAY_NOON_ET, backfill_sessions=150)
    assert len(second.skipped) == 7
    assert len(provider.calls) == calls_before, "a complete history must not call the provider"
    assert db.scalar(select(func.count()).select_from(PriceBar)) == count


def test_cache_miss_is_served_from_postgres_and_warms_redis(db: Session) -> None:
    client = get_redis()
    assert client is not None
    populate(db, MONDAY_NOON_ET)
    client.flushdb()

    result = md.read_quotes(db, client, md.big7_tickers(db))
    assert len(result.quotes) == 7
    assert len(result.cache_misses) == 7
    assert client.exists("quote:MSFT")

    again = md.read_quotes(db, client, md.big7_tickers(db))
    assert again.cache_misses == []


def test_cache_read_survives_redis_being_absent(db: Session) -> None:
    populate(db, MONDAY_NOON_ET)
    result = md.read_quotes(db, None, md.big7_tickers(db))
    assert len(result.quotes) == 7


def test_intraday_signal_uses_the_live_price(db: Session) -> None:
    populate(db, MONDAY_NOON_ET)
    snapshot = db.scalars(
        select(SignalSnapshot).order_by(SignalSnapshot.computed_at.desc())
    ).first()
    assert snapshot is not None
    inputs = snapshot.components_json["inputs"]
    assert inputs["intraday"] is True
    assert inputs["as_of_session"] == "2026-09-14"

    live = db.scalar(select(LatestQuote.price).where(LatestQuote.ticker_id == snapshot.ticker_id))
    assert inputs["last_price"] == round(live, 4)
    assert snapshot.source == "simulated"


def test_signal_on_a_closed_market_uses_completed_bars_only(db: Session) -> None:
    populate(db, SATURDAY_NOON_ET)
    snapshots = db.scalars(select(SignalSnapshot)).all()
    assert len(snapshots) == 7
    assert all(s.components_json["inputs"]["intraday"] is False for s in snapshots)
    assert all(
        s.components_json["inputs"]["as_of_session"] == FRIDAY.isoformat() for s in snapshots
    )


def test_no_bars_means_no_signal_not_a_crash(db: Session) -> None:
    result = md.compute_signals(db, md.big7_tickers(db), MONDAY_NOON_ET, None)
    assert result.updated == []
    assert len(result.skipped) == 7


def test_recent_bars_returns_the_latest_n_oldest_first(db: Session) -> None:
    populate(db, SATURDAY_NOON_ET)
    tickers = md.big7_tickers(db)
    bars = md.recent_bars(db, [tickers[0].id], 8)[tickers[0].id]
    dates = [b.session_date for b in bars]
    assert len(bars) == 8
    assert dates == sorted(dates)
    assert dates[-1] == FRIDAY
