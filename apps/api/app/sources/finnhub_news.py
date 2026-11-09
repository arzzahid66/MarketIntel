"""Finnhub company news.

Verified available on the free tier (`/company-news` returns 200 where
`/stock/candle` returns 403), which makes it the shortest path to real
headlines for the Big 7.

It shares the `finnhub` token bucket with the quote provider, because both spend
the same per-minute budget against the same key - giving news its own bucket
would let the two of them together exceed the published limit.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

import httpx

from app.services.rate_limit import TokenBucket
from app.sources.base import RawArticle, SourceError, SourceRateLimited

BASE_URL = "https://finnhub.io/api/v1"


class FinnhubNewsSource:
    name = "finnhub"

    def __init__(
        self,
        api_key: str,
        bucket: TokenBucket,
        client: httpx.Client | None = None,
        timeout: float = 8.0,
    ) -> None:
        if not api_key:
            raise ValueError("Finnhub news requires an API key")
        self._bucket = bucket
        self._client = client or httpx.Client(base_url=BASE_URL, timeout=timeout)
        self._headers = {"X-Finnhub-Token": api_key, "Accept": "application/json"}

    def fetch(self, symbol: str, since: date, until: date) -> list[RawArticle]:
        self._bucket.acquire()
        params = {"symbol": symbol, "from": since.isoformat(), "to": until.isoformat()}
        try:
            response = self._client.get("/company-news", params=params, headers=self._headers)
        except httpx.HTTPError as exc:
            raise SourceError(self.name, f"network error: {type(exc).__name__}") from exc

        if response.status_code == 429:
            raise SourceRateLimited(self.name, "rate limited")
        if response.status_code in (401, 403):
            raise SourceError(self.name, f"{response.status_code} (bad key or not in plan)")
        if response.status_code >= 400:
            raise SourceError(self.name, f"HTTP {response.status_code}")

        try:
            payload = response.json()
        except ValueError as exc:
            raise SourceError(self.name, "non-JSON response") from exc
        if not isinstance(payload, list):
            raise SourceError(self.name, f"expected a list, got {type(payload).__name__}")

        articles = [a for a in (_article(row) for row in payload) if a is not None]
        return sorted(articles, key=lambda a: a.published_at, reverse=True)


def _article(row: Any) -> RawArticle | None:
    """One Finnhub row, or None if it is not citable.

    Rows missing a headline, URL or timestamp are dropped rather than stored
    with placeholders: rule 4 requires every row to carry a real source.
    """
    if not isinstance(row, dict):
        return None
    title = (row.get("headline") or "").strip()
    url = (row.get("url") or "").strip()
    stamp = row.get("datetime")
    if not title or not url or not stamp:
        return None
    try:
        published_at = datetime.fromtimestamp(int(stamp), UTC)
    except (TypeError, ValueError, OSError, OverflowError):
        return None

    summary = (row.get("summary") or "").strip() or None
    # Finnhub repeats the headline as the summary often enough to be worth
    # dropping: it costs prompt tokens and tells the model nothing new.
    if summary and summary.casefold() == title.casefold():
        summary = None

    return RawArticle(
        title=title,
        summary=summary,
        url=url,
        publisher=(row.get("source") or "unknown").strip() or "unknown",
        published_at=published_at,
    )
