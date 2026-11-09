"""Scheduled market events (Phase 5).

Only earnings for now, and the table is named for what it holds rather than for
the surface it feeds. The build plan asks for an "economic calendar"; Finnhub's
free tier returns **403** on `/calendar/economic`, so macro prints need a source
the client has not yet chosen (section 6). `/calendar/earnings` is free and
returns the whole forward calendar, so that is what ships - labelled as
earnings, not passed off as macro.

Events are upserted on `(symbol, session_date)`: estimates get revised and the
reported figure lands after the fact, so the same row is written many times.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, Float, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, uuid_pk


class EarningsEvent(Base, TimestampMixin):
    """One company's scheduled or reported results for one date."""

    __tablename__ = "earnings_events"
    __table_args__ = (
        # One row per company per date. The ingest upserts onto this.
        UniqueConstraint("symbol", "session_date", name="uq_earnings_symbol_date"),
        # The read path: the next N days, soonest first.
        Index("ix_earnings_session_date", "session_date"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()

    #: Stored as text, not a ticker FK: the provider returns the entire market's
    #: calendar, and most of those symbols are not in our universe. `ticker_id`
    #: is filled in when we do follow one, so a join is still possible.
    symbol: Mapped[str] = mapped_column(String(16), nullable=False)
    ticker_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("tickers.id", ondelete="SET NULL"), nullable=True
    )

    session_date: Mapped[date] = mapped_column(Date, nullable=False)
    #: "bmo" (before market open), "amc" (after market close), or "" when the
    #: provider does not say. Kept as the provider's own token rather than an
    #: enum, because a new token must not break ingest.
    timing: Mapped[str] = mapped_column(String(8), nullable=False, default="")

    fiscal_quarter: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fiscal_year: Mapped[int | None] = mapped_column(Integer, nullable=True)

    eps_estimate: Mapped[float | None] = mapped_column(Float, nullable=True)
    eps_actual: Mapped[float | None] = mapped_column(Float, nullable=True)
    revenue_estimate: Mapped[float | None] = mapped_column(Float, nullable=True)
    revenue_actual: Mapped[float | None] = mapped_column(Float, nullable=True)

    source: Mapped[str] = mapped_column(String(32), nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    def __repr__(self) -> str:
        return f"<EarningsEvent {self.symbol} {self.session_date}>"
