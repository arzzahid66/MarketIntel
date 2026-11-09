"""The news feed endpoint.

Free for everyone, per the plan's access table. Reads only what the worker has
already ingested and scored - no source call, no LLM call, so a slow model can
make the feed staler but never a page slower.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.auth.deps import DbSession
from app.core.clock import Clock, get_clock
from app.models.feed import FeedItem
from app.schemas.feed import FeedCategoryOut, FeedItemOut, FeedOut, FeedTickerOut
from app.services import feed as feed_service

router = APIRouter(prefix="/feed", tags=["feed"])

ClockDep = Annotated[Clock, Depends(get_clock)]

#: Enough to fill the panel without turning one request into a long scan.
MAX_ITEMS = 100


def _item(item: FeedItem) -> FeedItemOut:
    scored = [link for link in item.tickers if link.scored_at is not None]
    return FeedItemOut(
        id=str(item.id),
        summary=item.ai_summary or item.summary,
        summary_is_ai=bool(item.ai_summary),
        title=item.title,
        source_url=item.source_url,
        publisher=item.publisher,
        published_at=item.published_at,
        fetched_at=item.fetched_at,
        category=(
            FeedCategoryOut(key=item.category.key, label=item.category.label)
            if item.category
            else None
        ),
        tickers=[
            FeedTickerOut(
                symbol=link.ticker.symbol,
                sentiment=link.sentiment,
                label=link.label,
                materiality=link.materiality,
                rationale=link.rationale,
            )
            # Sorted strongest-first: the reader cares which company this moves most.
            for link in sorted(scored, key=lambda link: -abs(link.sentiment or 0.0))
        ],
    )


@router.get("", response_model=FeedOut)
def get_feed(
    db: DbSession,
    clock: ClockDep,
    limit: Annotated[int, Query(ge=1, le=MAX_ITEMS)] = 30,
    category: str | None = None,
    symbol: str | None = None,
) -> FeedOut:
    items = feed_service.recent_items(db, limit=limit, category_key=category, symbol=symbol)
    return FeedOut(
        server_time=clock(),
        categories=[FeedCategoryOut(key=c.key, label=c.label) for c in feed_service.categories(db)],
        items=[_item(item) for item in items],
    )
