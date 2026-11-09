from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, uuid_pk

if TYPE_CHECKING:
    from app.models.ticker import Ticker
    from app.models.user import User


class Watchlist(Base, TimestampMixin):
    """A user's custom dashboard. Item count is capped by the plan, server-side."""

    __tablename__ = "watchlists"
    __table_args__ = (UniqueConstraint("user_id", "name", name="uq_watchlist_user_name"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String(64), default="My dashboard", nullable=False)
    is_default: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    user: Mapped[User] = relationship(back_populates="watchlists")
    items: Mapped[list[WatchlistItem]] = relationship(
        back_populates="watchlist",
        cascade="all, delete-orphan",
        order_by="WatchlistItem.position",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<Watchlist {self.name} user={self.user_id}>"


class WatchlistItem(Base, TimestampMixin):
    """Separate from `watchlists` because Phase 4 lets users reorder tickers."""

    __tablename__ = "watchlist_items"
    __table_args__ = (
        UniqueConstraint("watchlist_id", "ticker_id", name="uq_watchlist_item_ticker"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    watchlist_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("watchlists.id", ondelete="CASCADE"), index=True, nullable=False
    )
    ticker_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tickers.id", ondelete="CASCADE"), index=True, nullable=False
    )
    position: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    watchlist: Mapped[Watchlist] = relationship(back_populates="items")
    ticker: Mapped[Ticker] = relationship(lazy="joined")

    def __repr__(self) -> str:
        return f"<WatchlistItem {self.ticker_id} @{self.position}>"
