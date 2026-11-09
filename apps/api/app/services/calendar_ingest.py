"""Earnings calendar ingest. One request for the market, upserted by (symbol, date).

The source returns the entire market's calendar, not just our universe. We store
all of it and resolve `ticker_id` where we follow the name, because:

  * one request for the market costs the same as one for a symbol, and
  * a company we add to the universe next week already has its calendar, with no
    backfill.

Upsert rather than insert: an estimate gets revised, and the reported figure
lands days after the row was first written. The unique constraint on
`(symbol, session_date)` is what makes a re-run harmless.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging import get_logger
from app.models.calendar import EarningsEvent
from app.models.ticker import Ticker
from app.sources.calendar_base import EarningsCalendarSource, RawEarnings, SourceError

log = get_logger("services.calendar_ingest")


@dataclass
class CalendarIngestResult:
    fetched: int = 0
    written: int = 0
    followed: int = 0
    failed: str | None = None


def ingest_window(now: datetime) -> tuple[date, date]:
    """The window to ask for, from the injected clock.

    Reaches backwards as well as forwards so a result reported yesterday still
    shows its actual beside the estimate instead of vanishing from the panel the
    moment it is announced.
    """
    today = now.date()
    return (
        today - timedelta(days=settings.calendar_lookback_days),
        today + timedelta(days=settings.calendar_horizon_days),
    )


def ingest_earnings(
    db: Session,
    source: EarningsCalendarSource,
    now: datetime,
) -> CalendarIngestResult:
    since, until = ingest_window(now)
    try:
        events = source.fetch(since, until)
    except SourceError as exc:
        # One dead calendar must not take the run down: the panel keeps showing
        # what it already has, and the next cycle tries again.
        log.warning("calendar_fetch_failed", error=str(exc))
        return CalendarIngestResult(failed=str(exc))

    if not events:
        return CalendarIngestResult()

    ticker_ids = dict(
        db.execute(select(Ticker.symbol, Ticker.id).where(Ticker.is_active.is_(True)))
        .tuples()
        .all()
    )

    written = 0
    followed = 0
    for event in events:
        ticker_id = ticker_ids.get(event.symbol)
        if ticker_id is not None:
            followed += 1
        written += _upsert(db, event, ticker_id, source.name, now)

    db.commit()
    return CalendarIngestResult(
        fetched=len(events), written=written, followed=followed, failed=None
    )


def _upsert(
    db: Session,
    event: RawEarnings,
    ticker_id: object | None,
    source_name: str,
    now: datetime,
) -> int:
    """Insert or update one event. Returns 1 always - the row is current either way.

    `ON CONFLICT DO UPDATE`, not `DO NOTHING`: the whole reason to re-fetch a
    date we already hold is that the estimate moved or the actual landed.
    """
    values = {
        "symbol": event.symbol,
        "ticker_id": ticker_id,
        "session_date": event.session_date,
        "timing": event.timing,
        "fiscal_quarter": event.fiscal_quarter,
        "fiscal_year": event.fiscal_year,
        "eps_estimate": event.eps_estimate,
        "eps_actual": event.eps_actual,
        "revenue_estimate": event.revenue_estimate,
        "revenue_actual": event.revenue_actual,
        "source": source_name,
        "fetched_at": now,
    }
    statement = (
        insert(EarningsEvent)
        .values(**values)
        .on_conflict_do_update(
            constraint="uq_earnings_symbol_date",
            set_={
                key: values[key]
                for key in (
                    "ticker_id",
                    "timing",
                    "fiscal_quarter",
                    "fiscal_year",
                    "eps_estimate",
                    "eps_actual",
                    "revenue_estimate",
                    "revenue_actual",
                    "source",
                    "fetched_at",
                )
            },
        )
    )
    db.execute(statement)
    return 1
