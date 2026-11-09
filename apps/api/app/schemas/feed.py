"""Feed response shapes.

Every item carries `source_url` and `publisher` because rule 4 is not just a
storage rule: the citation has to reach the reader, or the feed is a wall of
unattributable claims.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class FeedCategoryOut(BaseModel):
    key: str
    label: str


class FeedTickerOut(BaseModel):
    symbol: str
    sentiment: float | None
    label: str | None
    materiality: str | None
    rationale: str | None


class FeedItemOut(BaseModel):
    id: str
    title: str
    #: The LLM's one-line summary when scored, else the publisher's own.
    summary: str | None
    #: True when `summary` was written by the model rather than the publisher,
    #: so the UI can attribute it honestly.
    summary_is_ai: bool
    source_url: str
    publisher: str
    published_at: datetime
    fetched_at: datetime
    category: FeedCategoryOut | None
    tickers: list[FeedTickerOut]


class FeedOut(BaseModel):
    server_time: datetime
    categories: list[FeedCategoryOut]
    items: list[FeedItemOut]
