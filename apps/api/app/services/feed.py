"""The news feed: ingest, deduplicate, score, read.

The shape mirrors `market_data.py`, and for the same reasons. Nothing here is
called from a request path - pages read what the worker has already written, so
a slow source or a slow model can make the feed staler but never a page slower.

Cost discipline is the other constraint, and it is structural rather than
advisory:

  * Dedup runs **before** scoring, so a wire story syndicated five times is paid
    for once.
  * An article is scored **once per company**, at ingest, and the result is
    stored. Nothing re-scores on read, so cost tracks news volume, not traffic.
  * Scoring is batched (`news_score_batch`) and failures are counted, so one
    unparseable article cannot be retried forever.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging import get_logger
from app.llm.base import LLMClient, LLMError
from app.models.feed import FeedCategory, FeedItem, FeedItemTicker
from app.models.ticker import Ticker
from app.services import news_sentiment as ns
from app.services.dedup import (
    NEAR_DUPLICATE_BITS,
    canonical_url,
    is_near_duplicate,
    simhash,
)
from app.sources.base import NewsSource, RawArticle, SourceError

log = get_logger("services.feed")

#: Near-duplicate search window. Syndication happens within hours, so comparing
#: a new article against a week of titles is wasted work.
DUPLICATE_WINDOW = timedelta(days=2)


@dataclass
class IngestResult:
    inserted: int = 0
    duplicates: int = 0
    linked: int = 0
    failed: dict[str, str] = field(default_factory=dict)

    @property
    def seen(self) -> int:
        return self.inserted + self.duplicates

    @property
    def duplicate_rate(self) -> float:
        """Share of fetched articles that were already known. The Phase 3 exit
        criterion is measured on this."""
        return self.duplicates / self.seen if self.seen else 0.0


@dataclass
class ScoreResult:
    scored: int = 0
    skipped: int = 0
    failed: dict[str, str] = field(default_factory=dict)


def categories(db: Session) -> list[FeedCategory]:
    return list(
        db.scalars(
            select(FeedCategory)
            .where(FeedCategory.is_active.is_(True))
            .order_by(FeedCategory.sort_order)
        )
    )


def category_choices(db: Session) -> list[ns.CategoryChoice]:
    """The taxonomy as the classifier is shown it."""
    return [ns.CategoryChoice(key=c.key, description=c.description) for c in categories(db)]


# ---------------------------------------------------------------------------
# Ingest
# ---------------------------------------------------------------------------


def _recent_hashes(db: Session, now: datetime) -> list[tuple[int, FeedItem]]:
    since = now - DUPLICATE_WINDOW
    rows = db.scalars(
        select(FeedItem).where(FeedItem.published_at >= since).order_by(FeedItem.published_at)
    )
    return [(item.title_hash, item) for item in rows]


def ingest_for_ticker(
    db: Session,
    source: NewsSource,
    ticker: Ticker,
    now: datetime,
    backfill_days: int,
) -> IngestResult:
    """Fetch, deduplicate and store one ticker's news. Never scores."""
    result = IngestResult()
    until = now.date()
    since = until - timedelta(days=backfill_days)

    try:
        articles = source.fetch(ticker.symbol, since, until)
    except SourceError as exc:
        result.failed[ticker.symbol] = str(exc)
        return result

    known = _recent_hashes(db, now)
    for raw in articles:
        item, is_new = _upsert_article(db, source, raw, now, known)
        if item is None:
            result.duplicates += 1
            continue
        if is_new:
            result.inserted += 1
            known.append((item.title_hash, item))
        else:
            result.duplicates += 1
        if _link_ticker(db, item, ticker):
            result.linked += 1

    db.commit()
    return result


def _upsert_article(
    db: Session,
    source: NewsSource,
    raw: RawArticle,
    now: datetime,
    known: list[tuple[int, FeedItem]],
) -> tuple[FeedItem | None, bool]:
    """Insert an article, or return the existing row it duplicates.

    Returns (item, is_new). A near-duplicate returns the article it matched, so
    the new ticker is still linked to the story we already have - the reader
    sees one entry, and the signal counts the story once.
    """
    url = canonical_url(raw.url)

    existing = db.scalars(select(FeedItem).where(FeedItem.canonical_url == url)).first()
    if existing is not None:
        return existing, False

    fingerprint = simhash(raw.title)
    for other_hash, other in known:
        if is_near_duplicate(fingerprint, other_hash):
            log.debug("feed_near_duplicate", title=raw.title[:80], matched=other.title[:80])
            return other, False

    item = FeedItem(
        title=raw.title,
        summary=raw.summary,
        source_url=raw.url,
        canonical_url=url,
        publisher=raw.publisher,
        published_at=raw.published_at,
        fetched_at=now,
        source=source.name,
        title_hash=fingerprint,
    )
    db.add(item)
    try:
        # Two workers can race on the same article; the unique constraint is the
        # authority, not the SELECT above.
        db.flush()
    except Exception:
        db.rollback()
        return db.scalars(select(FeedItem).where(FeedItem.canonical_url == url)).first(), False
    return item, True


def _link_ticker(db: Session, item: FeedItem, ticker: Ticker) -> bool:
    """Attach an article to a company. Idempotent; returns whether it was new.

    RETURNING rather than rowcount: after ON CONFLICT DO NOTHING, rowcount does
    not distinguish "inserted" from "already there", so the ingest log silently
    reported zero new links while writing thousands of them.
    """
    statement = (
        insert(FeedItemTicker)
        .values(feed_item_id=item.id, ticker_id=ticker.id)
        .on_conflict_do_nothing(constraint="uq_feed_item_ticker")
        .returning(FeedItemTicker.id)
    )
    return db.execute(statement).first() is not None


def ingest_news(
    db: Session,
    source: NewsSource,
    tickers: list[Ticker],
    now: datetime,
    backfill_days: int | None = None,
) -> IngestResult:
    days = backfill_days if backfill_days is not None else settings.news_backfill_days
    total = IngestResult()
    for ticker in tickers:
        one = ingest_for_ticker(db, source, ticker, now, days)
        total.inserted += one.inserted
        total.duplicates += one.duplicates
        total.linked += one.linked
        total.failed.update(one.failed)
    return total


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


def unscored(db: Session, limit: int, max_attempts: int) -> list[FeedItemTicker]:
    """Article-company pairs still needing a score, newest first.

    Newest first because a fresh headline carries the most weight in the signal;
    if a backlog never fully drains, the part that matters is already done.
    """
    return list(
        db.scalars(
            select(FeedItemTicker)
            .join(FeedItem)
            .where(
                FeedItemTicker.scored_at.is_(None),
                FeedItemTicker.failed_attempts < max_attempts,
            )
            .order_by(FeedItem.published_at.desc())
            .limit(limit)
        )
    )


def score_pending(
    db: Session,
    client: LLMClient,
    now: datetime,
    limit: int | None = None,
    max_attempts: int | None = None,
) -> ScoreResult:
    """Score a batch of article-company pairs. One LLM call each, then stored."""
    limit = limit if limit is not None else settings.news_score_batch
    max_attempts = max_attempts if max_attempts is not None else settings.news_max_score_attempts
    choices = category_choices(db)
    by_key = {c.key: c for c in categories(db)}
    result = ScoreResult()

    for link in unscored(db, limit, max_attempts):
        item = link.item
        article = ns.Article(
            headline=item.title,
            summary=item.summary,
            url=item.source_url,
            publisher=item.publisher,
            published_at=item.published_at,
        )
        try:
            assessment = ns.assess_article(
                client, article, link.ticker.name, link.ticker.symbol, choices
            )
        except LLMError as exc:
            # Counted, not hidden: a pair that fails `max_attempts` times stops
            # being retried and shows up in the log with its reason.
            link.failed_attempts += 1
            link.last_error = str(exc)[:500]
            result.failed[item.title[:60]] = str(exc)
            result.skipped += 1
            continue

        sentiment = assessment.sentiment
        link.sentiment = sentiment.score
        link.label = sentiment.label
        link.materiality = sentiment.materiality
        link.rationale = sentiment.rationale
        link.scored_at = now
        link.model = sentiment.model
        link.prompt_version = sentiment.prompt_version
        link.last_error = None

        # Category and summary describe the article, so only the first scoring
        # of a multi-company story writes them.
        if item.classified_at is None:
            category = by_key.get(assessment.category_key or "")
            item.category_id = category.id if category else None
            item.ai_summary = assessment.ai_summary or None
            item.classified_at = now
            item.model = sentiment.model
            item.prompt_version = sentiment.prompt_version

        result.scored += 1

    db.commit()
    return result


# ---------------------------------------------------------------------------
# Embeddings, for the AI analyst's retrieval
# ---------------------------------------------------------------------------


def embedding_text(item: FeedItem) -> str:
    """What gets embedded: the headline plus whichever summary we have.

    The publisher's summary is preferred over the model's, because the model's
    was written from the headline and adds little the headline did not already
    say. Capped - an embedding of a whole article dilutes the subject.
    """
    body = item.summary or item.ai_summary or ""
    return f"{item.title}\n\n{body}".strip()[:4000]


def embed_pending(
    db: Session,
    client: LLMClient,
    now: datetime,
    limit: int = 64,
) -> ScoreResult:
    """Embed a batch of articles that do not have a vector yet.

    Re-embeds nothing: a vector costs money once and never changes. Articles
    embedded by a *different* model are also picked up, because vectors from two
    models cannot be compared and mixing them quietly corrupts retrieval.
    """
    result = ScoreResult()
    items = list(
        db.scalars(
            select(FeedItem)
            .where(
                (FeedItem.embedding.is_(None))
                | (FeedItem.embedding_model != client.embedding_model)
            )
            .order_by(FeedItem.published_at.desc())
            .limit(limit)
        )
    )
    if not items:
        return result

    try:
        vectors = client.embed([embedding_text(item) for item in items])
    except LLMError as exc:
        # The whole batch shares one request, so one failure skips all of them;
        # the next cycle picks the same articles up again.
        log.warning("embed_failed", error=str(exc), batch=len(items))
        result.failed["batch"] = str(exc)
        result.skipped = len(items)
        return result

    for item, vector in zip(items, vectors, strict=True):
        item.embedding = vector
        item.embedded_at = now
        item.embedding_model = client.embedding_model
        result.scored += 1
    db.commit()
    return result


# ---------------------------------------------------------------------------
# Reads - the signal's input, and the feed page
# ---------------------------------------------------------------------------


def sentiment_for_tickers(
    db: Session,
    ticker_ids: list[uuid.UUID],
    now: datetime,
    lookback_days: int = ns.LOOKBACK_DAYS,
) -> dict[uuid.UUID, float]:
    """Per-ticker `news_sentiment_7d`, ready for `compute_signal`.

    Tickers with no scored news in the window are **absent from the result**,
    not zero: `compute_signal` treats a missing value as unavailable and says so
    in the breakdown, where zero would silently vote neutral.
    """
    cutoff = now - timedelta(days=lookback_days)
    rows = db.execute(
        select(FeedItemTicker, FeedItem.published_at)
        .join(FeedItem)
        .where(
            FeedItemTicker.ticker_id.in_(ticker_ids),
            FeedItemTicker.scored_at.is_not(None),
            FeedItem.published_at >= cutoff,
        )
    ).all()

    grouped: dict[uuid.UUID, list[ns.ScoredArticle]] = {}
    for link, published_at in rows:
        article = ns.Article(
            headline="", summary=None, url="", publisher="", published_at=published_at
        )
        sentiment = ns.ArticleSentiment(
            score=float(link.sentiment or 0.0),
            label=link.label or "neutral",
            materiality=link.materiality or "low",
            rationale=link.rationale or "",
            model=link.model or "",
            prompt_version=link.prompt_version or 0,
        )
        grouped.setdefault(link.ticker_id, []).append(ns.ScoredArticle(article, sentiment))

    out: dict[uuid.UUID, float] = {}
    for ticker_id, scored in grouped.items():
        value = ns.aggregate_7d(scored, now, lookback_days=lookback_days)
        if value is not None:
            out[ticker_id] = value
    return out


def recent_items(
    db: Session,
    limit: int = 30,
    category_key: str | None = None,
    symbol: str | None = None,
) -> list[FeedItem]:
    """The feed, newest first, optionally filtered."""
    statement = select(FeedItem).order_by(FeedItem.published_at.desc()).limit(limit)
    if category_key:
        statement = statement.join(FeedCategory).where(FeedCategory.key == category_key)
    if symbol:
        statement = statement.join(FeedItemTicker).join(Ticker).where(Ticker.symbol == symbol)
    return list(db.scalars(statement).unique())


def surviving_duplicate_rate(
    db: Session,
    now: datetime,
    window_days: int = 2,
    sample_limit: int = 2000,
    max_bits: int = NEAR_DUPLICATE_BITS,
) -> tuple[float, int, int]:
    """Share of stored articles that duplicate an earlier stored article.

    **This is the Phase 3 exit criterion**, and it is not the same number as
    `IngestResult.duplicate_rate`. That one counts duplicates the pipeline
    *caught* on the way in - it rises as the source repeats itself, and a high
    value is good news. This one counts duplicates that got *through* and are
    sitting in the feed where a reader can see the same story twice. The target
    is under 5%.

    Returns (rate, duplicates_found, sampled). Compared within `window_days`
    because syndication happens within hours, matching `DUPLICATE_WINDOW`; the
    comparison is quadratic, so the sample is capped.

    At the default `max_bits` this is partly self-confirming - it uses the same
    fingerprint the ingest filter used, so it can only find what that filter
    would also have caught, and the honest reading of 0% is "no duplicates our
    own method can see". Raise `max_bits` above NEAR_DUPLICATE_BITS to look for
    the pairs the production threshold let through; that gap is the real
    evidence for whether the threshold is set correctly.
    """
    since = now - timedelta(days=window_days)
    rows = db.execute(
        select(FeedItem.title_hash, FeedItem.published_at)
        .where(FeedItem.published_at >= since)
        .order_by(FeedItem.published_at)
        .limit(sample_limit)
    ).all()

    kept: list[int] = []
    duplicates = 0
    for title_hash, _published_at in rows:
        if any(is_near_duplicate(title_hash, other, max_bits) for other in kept):
            duplicates += 1
        else:
            kept.append(title_hash)

    sampled = len(rows)
    return (duplicates / sampled if sampled else 0.0), duplicates, sampled


def feed_stats(db: Session, now: datetime) -> dict[str, int]:
    """Counts for the health endpoint and the 72-hour soak check."""
    day_ago = now - timedelta(days=1)
    return {
        "items": db.scalar(select(func.count(FeedItem.id))) or 0,
        "items_last_24h": db.scalar(
            select(func.count(FeedItem.id)).where(FeedItem.fetched_at >= day_ago)
        )
        or 0,
        "unscored": db.scalar(
            select(func.count(FeedItemTicker.id)).where(FeedItemTicker.scored_at.is_(None))
        )
        or 0,
    }
