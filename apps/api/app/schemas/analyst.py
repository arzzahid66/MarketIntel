"""AI analyst request and response shapes."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class AskIn(BaseModel):
    #: Bounded so a pasted document cannot be smuggled in as a question - it
    #: would cost a large prompt and swamp the retrieved articles.
    question: str = Field(min_length=3, max_length=2000)
    #: Optional: restrict retrieval to one company's articles.
    symbol: str | None = Field(default=None, max_length=10)


class CitationOut(BaseModel):
    number: int
    feed_item_id: str
    title: str
    publisher: str
    source_url: str
    published_at: datetime


class UsageOut(BaseModel):
    """What the viewer has left today. -1 means no ceiling (fair use)."""

    used_today: int
    daily_limit: int
    used_this_hour: int
    hourly_limit: int


class AnswerOut(BaseModel):
    answer: str
    citations: list[CitationOut]
    #: How many articles were retrieved before the model saw them. Zero means
    #: the feed had nothing relevant, and the answer says so.
    retrieved: int
    model: str
    server_time: datetime
    usage: UsageOut


class AnalystStatusOut(BaseModel):
    """Lets the page show the quota before a question is asked."""

    server_time: datetime
    usage: UsageOut
    #: Articles currently searchable. Zero means the embed job has not run.
    searchable_articles: int
