"""Source registries: company news, and the earnings calendar.

    NEWS_SOURCE=fake    -> the deterministic stub
    NEWS_SOURCE=finnhub -> Finnhub company news (needs FINNHUB_API_KEY)
    NEWS_SOURCE=auto    -> Finnhub if the key is set, else the stub

`CALENDAR_SOURCE` takes the same three values and resolves the same way.

Both reuse the `finnhub` token bucket rather than creating their own, so news,
the calendar and quotes together stay under the one published per-minute limit
for the key.
"""

from __future__ import annotations

from functools import lru_cache

from app.core.config import Settings, settings
from app.core.redis import get_redis
from app.services.rate_limit import TokenBucket
from app.sources.base import (
    NewsSource,
    RawArticle,
    SourceError,
    SourceRateLimited,
)
from app.sources.calendar_base import EarningsCalendarSource, RawEarnings
from app.sources.fake import FakeNewsSource
from app.sources.fake_calendar import FakeEarningsCalendar
from app.sources.finnhub_calendar import FinnhubEarningsCalendar
from app.sources.finnhub_news import FinnhubNewsSource


def build_news_source(config: Settings) -> NewsSource:
    key = config.finnhub_api_key.get_secret_value()
    mode = config.news_source
    if mode == "fake" or (mode == "auto" and not key):
        return FakeNewsSource()
    if not key:
        raise RuntimeError("NEWS_SOURCE=finnhub but FINNHUB_API_KEY is not set")
    return FinnhubNewsSource(
        key,
        TokenBucket("finnhub", config.finnhub_calls_per_minute, client=get_redis()),
        timeout=config.provider_timeout_seconds,
    )


@lru_cache(maxsize=1)
def get_news_source() -> NewsSource:
    return build_news_source(settings)


def build_calendar_source(config: Settings) -> EarningsCalendarSource:
    key = config.finnhub_api_key.get_secret_value()
    mode = config.calendar_source
    if mode == "fake" or (mode == "auto" and not key):
        return FakeEarningsCalendar()
    if not key:
        raise RuntimeError("CALENDAR_SOURCE=finnhub but FINNHUB_API_KEY is not set")
    return FinnhubEarningsCalendar(
        key,
        TokenBucket("finnhub", config.finnhub_calls_per_minute, client=get_redis()),
        timeout=config.provider_timeout_seconds,
    )


@lru_cache(maxsize=1)
def get_calendar_source() -> EarningsCalendarSource:
    return build_calendar_source(settings)


__all__ = [
    "EarningsCalendarSource",
    "FakeEarningsCalendar",
    "FakeNewsSource",
    "FinnhubEarningsCalendar",
    "FinnhubNewsSource",
    "NewsSource",
    "RawArticle",
    "RawEarnings",
    "SourceError",
    "SourceRateLimited",
    "build_calendar_source",
    "build_news_source",
    "get_calendar_source",
    "get_news_source",
]
