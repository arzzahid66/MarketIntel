"""Market data persistence (Phase 2).

Redis is the fast path; these tables are the durable one. If Redis is flushed or
down, the dashboard rebuilds from `latest_quotes` - that is what lets a provider
or cache outage degrade to last-known values instead of an empty table.

Every row records its `source`, so simulated data can never be passed off as
real, and every signal records the inputs it was computed from.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    BigInteger,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, uuid_pk

if TYPE_CHECKING:
    from app.models.ticker import Ticker

#: Prices as exact decimals in the database, floats in Python.
Price = Numeric(18, 4, asdecimal=False)


class PriceBar(Base):
    """One completed daily session. Immutable once the session has closed."""

    __tablename__ = "price_bars"
    # The unique constraint's index also serves "bars for ticker X, by date".
    __table_args__ = (UniqueConstraint("ticker_id", "session_date", name="uq_price_bar_session"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    ticker_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tickers.id", ondelete="CASCADE"), nullable=False
    )
    session_date: Mapped[date] = mapped_column(Date, nullable=False)
    open: Mapped[float] = mapped_column(Price, nullable=False)
    high: Mapped[float] = mapped_column(Price, nullable=False)
    low: Mapped[float] = mapped_column(Price, nullable=False)
    close: Mapped[float] = mapped_column(Price, nullable=False)
    volume: Mapped[int] = mapped_column(BigInteger, nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    ticker: Mapped[Ticker] = relationship()


class LatestQuote(Base):
    """The last quote we successfully fetched for a ticker. One row per ticker."""

    __tablename__ = "latest_quotes"

    ticker_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tickers.id", ondelete="CASCADE"), primary_key=True
    )
    price: Mapped[float] = mapped_column(Price, nullable=False)
    change: Mapped[float | None] = mapped_column(Price, nullable=True)
    change_percent: Mapped[float | None] = mapped_column(
        Numeric(12, 6, asdecimal=False), nullable=True
    )
    previous_close: Mapped[float | None] = mapped_column(Price, nullable=True)
    open: Mapped[float | None] = mapped_column(Price, nullable=True)
    high: Mapped[float | None] = mapped_column(Price, nullable=True)
    low: Mapped[float | None] = mapped_column(Price, nullable=True)
    #: When the provider observed the price.
    provider_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    #: When we fetched it. Staleness is judged on this, by the server clock.
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False)

    ticker: Mapped[Ticker] = relationship()


class SignalSnapshot(Base):
    """A computed signal, with enough detail to reproduce and explain it."""

    __tablename__ = "signal_snapshots"
    __table_args__ = (Index("ix_signal_snapshots_ticker_computed", "ticker_id", "computed_at"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    ticker_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tickers.id", ondelete="CASCADE"), nullable=False
    )
    score: Mapped[float] = mapped_column(Numeric(5, 1, asdecimal=False), nullable=False)
    band: Mapped[str] = mapped_column(String(20), nullable=False)
    formula_version: Mapped[int] = mapped_column(Integer, nullable=False)
    components_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    #: The data source the inputs came from - "simulated" signals stay labelled.
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    ticker: Mapped[Ticker] = relationship()
