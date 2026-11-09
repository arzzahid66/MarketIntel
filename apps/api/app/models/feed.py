"""News and social feed persistence (Phase 3).

Three tables, and the split between them is the important part:

  * `feed_categories` - categories are **rows, not an enum**, so adding "AI" or
    renaming "central banks" is a database change, not a migration and deploy.
  * `feed_items` - one row per article, deduplicated on `canonical_url`. Carries
    `source_url`, `fetched_at` and `publisher` on every row (non-negotiable rule
    4): that is what makes an AI answer citable and the product defensible.
  * `feed_item_tickers` - which companies an article is about, **and the
    sentiment for each of them separately**. The same article is good news for
    one company and bad for another ("Apple drops Qualcomm modems"), so
    sentiment cannot live on the article.

Scoring columns record `model` and `prompt_version` next to the score, because a
signal a customer saw has to be reproducible, and both change over time.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, uuid_pk

if TYPE_CHECKING:
    from app.models.ticker import Ticker

#: Sentiment in [-1, 1], stored exactly rather than as a float.
Score = Numeric(6, 4, asdecimal=False)

#: text-embedding-3-small. Changing this needs a migration AND a re-embed:
#: vectors of different widths cannot be compared, so old rows go stale.
EMBEDDING_DIMENSIONS = 1536


class FeedCategory(Base, TimestampMixin):
    """A feed category. Data, so the taxonomy can change without a deploy."""

    __tablename__ = "feed_categories"

    id: Mapped[uuid.UUID] = uuid_pk()
    #: Stable identifier the model is asked to choose from, e.g. "earnings".
    key: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    label: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_active: Mapped[bool] = mapped_column(nullable=False, default=True)


class FeedItem(Base, TimestampMixin):
    """One article. Unique on `canonical_url`, which is how dedup is enforced."""

    __tablename__ = "feed_items"
    __table_args__ = (
        UniqueConstraint("canonical_url", name="uq_feed_item_canonical_url"),
        # The feed is always read newest-first, usually filtered by category.
        Index("ix_feed_item_published", "published_at"),
        Index("ix_feed_item_category_published", "category_id", "published_at"),
        # Near-duplicate detection: same story, different publisher and URL.
        Index("ix_feed_item_title_hash", "title_hash"),
        # Vector search for the AI analyst. The operator class must match the
        # distance operator the retrieval query uses (`<=>`, cosine), or the
        # planner silently ignores the index and scans every article.
        Index(
            "ix_feed_item_embedding",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    title: Mapped[str] = mapped_column(Text, nullable=False)
    #: The publisher's own summary, before any LLM touches it.
    summary: Mapped[str | None] = mapped_column(Text)
    #: Rule 4: where this came from, verbatim, for citation.
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    #: The same URL with tracking parameters and fragments stripped. Dedup key.
    canonical_url: Mapped[str] = mapped_column(Text, nullable=False)
    publisher: Mapped[str] = mapped_column(String(128), nullable=False)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    #: Rule 4: when our servers fetched it, on the server clock.
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    #: Which ingest source produced this row, e.g. "finnhub".
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    #: Simhash of the normalised title, for near-duplicate detection.
    title_hash: Mapped[int] = mapped_column(BigInteger, nullable=False)

    # --- Filled by the LLM at ingest, once, then never recomputed ---
    category_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("feed_categories.id", ondelete="SET NULL")
    )
    #: One-line neutral summary written at ingest. Cached forever: summarising
    #: per viewer instead of per article is how LLM cost outruns revenue.
    ai_summary: Mapped[str | None] = mapped_column(Text)
    classified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    model: Mapped[str | None] = mapped_column(String(64))
    prompt_version: Mapped[int | None] = mapped_column(Integer)

    #: text-embedding-3-small. Null until the embed job has run; the analyst
    #: simply cannot retrieve an article that has none yet.
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIMENSIONS))
    embedded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    embedding_model: Mapped[str | None] = mapped_column(String(64))

    category: Mapped[FeedCategory | None] = relationship(lazy="joined")
    tickers: Mapped[list[FeedItemTicker]] = relationship(
        back_populates="item", cascade="all, delete-orphan", lazy="selectin"
    )


class FeedItemTicker(Base):
    """An article's relevance to one company, with that company's sentiment."""

    __tablename__ = "feed_item_tickers"
    __table_args__ = (
        UniqueConstraint("feed_item_id", "ticker_id", name="uq_feed_item_ticker"),
        # "the last 7 days of scored news for ticker X" - the signal's query.
        Index("ix_feed_item_ticker_scored", "ticker_id", "scored_at"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    feed_item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("feed_items.id", ondelete="CASCADE"), nullable=False
    )
    ticker_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tickers.id", ondelete="CASCADE"), nullable=False
    )

    # --- Null until the scoring job has run. Set once, then never recomputed ---
    sentiment: Mapped[float | None] = mapped_column(Score)
    label: Mapped[str | None] = mapped_column(String(16))
    materiality: Mapped[str | None] = mapped_column(String(16))
    rationale: Mapped[str | None] = mapped_column(Text)
    scored_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    model: Mapped[str | None] = mapped_column(String(64))
    prompt_version: Mapped[int | None] = mapped_column(Integer)
    #: Set when scoring failed, so a poison article is skipped rather than
    #: retried forever. Counted, not hidden.
    failed_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(Text)

    item: Mapped[FeedItem] = relationship(back_populates="tickers")
    ticker: Mapped[Ticker] = relationship(lazy="joined")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
