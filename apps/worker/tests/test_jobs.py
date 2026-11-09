"""The Phase 2 ingest jobs, run exactly as the scheduler runs them, on a fixed clock."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.core.clock import fixed_clock
from app.core.redis import get_redis
from app.db.seed import BIG7, UNIVERSE
from app.db.session import SessionLocal
from app.models.calendar import EarningsEvent
from app.models.market import LatestQuote, PriceBar, SignalSnapshot
from app.models.ticker import Ticker
from app.providers.fake import FakeProvider
from sqlalchemy import func, select

from worker.jobs import make_jobs, quotes_needed, signals_needed
from worker.main import ordered_jobs, run_once

MONDAY_NOON_ET = datetime(2026, 9, 14, 16, 0, tzinfo=UTC)
MONDAY_CLOSE = datetime(2026, 9, 14, 20, 0, tzinfo=UTC)
SATURDAY_NOON_ET = datetime(2026, 9, 12, 16, 0, tzinfo=UTC)


def jobs_at(now: datetime) -> dict:
    return {
        job.id: job for job in make_jobs(lambda: FakeProvider(fixed_clock(now)), fixed_clock(now))
    }


def count(model) -> int:  # type: ignore[no-untyped-def]
    with SessionLocal() as db:
        return db.scalar(select(func.count()).select_from(model)) or 0


def test_startup_order_puts_bars_before_signals() -> None:
    order = [job.id for job in ordered_jobs(tuple(jobs_at(MONDAY_NOON_ET).values()))]
    assert order.index("ingest_daily_bars") < order.index("compute_signals")
    assert order.index("ingest_quotes") < order.index("compute_signals")
    assert set(order) == set(jobs_at(MONDAY_NOON_ET))


def test_a_fresh_deploy_fills_bars_quotes_and_signals_in_one_pass() -> None:
    jobs = tuple(jobs_at(MONDAY_NOON_ET).values())
    assert run_once(jobs) == 0

    # Bars and signals stay Big-7-only: the wider universe exists for the
    # heatmap, and scoring forty more tickers would multiply the LLM spend for
    # a surface that does not show a signal.
    assert count(PriceBar) >= len(BIG7) * 65
    assert count(SignalSnapshot) == len(BIG7)
    # Quotes cover everything, because the heatmap needs a price per name.
    assert count(LatestQuote) == len(BIG7) + len(UNIVERSE)

    client = get_redis()
    assert client is not None
    for job_id in (
        "ingest_daily_bars",
        "ingest_quotes",
        "ingest_universe_quotes",
        "ingest_earnings",
        "compute_signals",
        "refresh_profiles",
    ):
        assert client.exists(f"worker:heartbeat:{job_id}"), job_id
    assert client.exists("quote:AAPL")


def test_quotes_run_every_cycle_while_the_market_is_open() -> None:
    jobs = jobs_at(MONDAY_NOON_ET)
    jobs["ingest_quotes"].func()
    with SessionLocal() as db:
        assert quotes_needed(db, MONDAY_NOON_ET)


def test_after_the_close_quotes_are_fetched_once_for_the_closing_print() -> None:
    before_close = MONDAY_CLOSE - timedelta(minutes=1)
    jobs_at(before_close)["ingest_quotes"].func()

    after = MONDAY_CLOSE + timedelta(minutes=10)
    with SessionLocal() as db:
        assert quotes_needed(db, after), "quotes from before the bell are not the close"

    jobs_at(after)["ingest_quotes"].func()
    with SessionLocal() as db:
        assert not quotes_needed(db, after + timedelta(minutes=1))


def test_weekend_quote_job_is_a_no_op_once_fridays_close_is_held() -> None:
    jobs = jobs_at(SATURDAY_NOON_ET)
    jobs["ingest_quotes"].func()
    with SessionLocal() as db:
        first_fetch = db.scalar(select(func.max(LatestQuote.fetched_at)))
        assert not quotes_needed(db, SATURDAY_NOON_ET + timedelta(hours=1))
    jobs_at(SATURDAY_NOON_ET + timedelta(hours=1))["ingest_quotes"].func()
    with SessionLocal() as db:
        assert db.scalar(select(func.max(LatestQuote.fetched_at))) == first_fetch


def test_signals_are_not_recomputed_on_a_closed_market_without_new_data() -> None:
    jobs = jobs_at(SATURDAY_NOON_ET)
    jobs["ingest_daily_bars"].func()
    jobs["compute_signals"].func()
    assert count(SignalSnapshot) == 7

    later = SATURDAY_NOON_ET + timedelta(hours=3)
    with SessionLocal() as db:
        assert not signals_needed(db, later)
    jobs_at(later)["compute_signals"].func()
    assert count(SignalSnapshot) == 7


def test_signals_without_any_bars_wait_rather_than_fail() -> None:
    with SessionLocal() as db:
        assert not signals_needed(db, SATURDAY_NOON_ET)


def test_bar_job_is_idempotent() -> None:
    jobs = jobs_at(MONDAY_NOON_ET)
    jobs["ingest_daily_bars"].func()
    first = count(PriceBar)
    jobs["ingest_daily_bars"].func()
    assert count(PriceBar) == first


# ---------------------------------------------------------------------------
# Extended markets (Phase 5)
# ---------------------------------------------------------------------------


def test_the_wider_universe_is_quoted_but_never_scored_for_signals() -> None:
    """The flag that keeps forty extra tickers cheap.

    `is_big7` is the whole separation: quotes cover the universe so the heatmap
    has a price per name, while bars and signals - the expensive, LLM-adjacent
    half - stay on the seven. If this ever inverts, cost scales with the
    universe rather than with the product.
    """
    jobs = jobs_at(MONDAY_NOON_ET)
    jobs["ingest_quotes"].func()
    jobs["ingest_universe_quotes"].func()
    jobs["ingest_daily_bars"].func()
    jobs["compute_signals"].func()

    with SessionLocal() as db:
        big7_ids = set(
            db.scalars(select(Ticker.id).where(Ticker.is_big7.is_(True))).all()
        )
        signalled = set(db.scalars(select(SignalSnapshot.ticker_id)).all())
        barred = set(db.scalars(select(PriceBar.ticker_id)).all())

    assert count(LatestQuote) == len(BIG7) + len(UNIVERSE)
    assert signalled == big7_ids, "signals must stay on the Big 7"
    assert barred == big7_ids, "daily bars must stay on the Big 7"


def test_quotes_needed_is_scoped_so_the_slow_universe_cannot_retrigger_the_big7() -> None:
    """Regression: a shared `latest_quotes` table with two cadences.

    The universe refreshes every 5 minutes and the Big 7 every 60 seconds. A
    freshness check over *all* rows sees the universe's older `fetched_at` and
    concludes the Big 7 still need fetching - forever, every cycle after the
    close. Scoping the check is what stops that.
    """
    before_close = MONDAY_CLOSE - timedelta(minutes=1)
    after = MONDAY_CLOSE + timedelta(minutes=10)

    # The Big 7 get their closing print; the universe keeps its older quotes.
    jobs_at(before_close)["ingest_universe_quotes"].func()
    jobs_at(after)["ingest_quotes"].func()

    with SessionLocal() as db:
        assert not quotes_needed(db, after + timedelta(minutes=1)), (
            "the Big 7 are current; the universe's older rows must not say otherwise"
        )


def test_the_earnings_calendar_is_upserted_so_an_actual_can_land_later() -> None:
    """Re-running must revise a row, not duplicate or ignore it.

    The reason to re-fetch a date already held is precisely that the estimate
    moved or the reported figure arrived, so `ON CONFLICT DO UPDATE` is the
    behaviour under test - `DO NOTHING` would freeze the first guess forever.
    """
    jobs_at(MONDAY_NOON_ET)["ingest_earnings"].func()
    first = count(EarningsEvent)
    assert first > 0

    with SessionLocal() as db:
        row = db.scalars(select(EarningsEvent).limit(1)).one()
        symbol, session_date = row.symbol, row.session_date
        row.eps_actual = None
        row.eps_estimate = -99.0
        db.commit()

    jobs_at(MONDAY_NOON_ET)["ingest_earnings"].func()

    assert count(EarningsEvent) == first, "a re-run must not duplicate rows"
    with SessionLocal() as db:
        refreshed = db.scalars(
            select(EarningsEvent).where(
                EarningsEvent.symbol == symbol,
                EarningsEvent.session_date == session_date,
            )
        ).one()
        assert refreshed.eps_estimate != -99.0, "a re-run must overwrite a stale estimate"
