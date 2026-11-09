from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, uuid_pk


class Ticker(Base, TimestampMixin):
    """The instrument universe. Phase 2 attaches quotes and signal snapshots to these."""

    __tablename__ = "tickers"

    id: Mapped[uuid.UUID] = uuid_pk()
    symbol: Mapped[str] = mapped_column(String(16), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    exchange: Mapped[str | None] = mapped_column(String(32), nullable=True)
    sector: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    industry: Mapped[str | None] = mapped_column(String(120), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), default="USD", nullable=False)

    #: The free-tier "Big 7" homepage set.
    is_big7: Mapped[bool] = mapped_column(Boolean, default=False, index=True, nullable=False)
    big7_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Refreshed nightly by the fundamentals job (Phase 2).
    market_cap: Mapped[float | None] = mapped_column(Numeric(20, 0, asdecimal=False), nullable=True)
    profile_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    def __repr__(self) -> str:
        return f"<Ticker {self.symbol}>"
