"""A deterministic news source for development, tests and CI.

Generates a stable set of headlines per symbol and date, so the whole feed
pipeline - ingest, dedup, scoring, aggregation, the UI - runs without a key or a
network call, and two runs produce exactly the same rows.

It deliberately emits duplicates: the same wire story under two publishers with
different URLs, and one article linked twice with tracking parameters. A dedup
layer that is never given duplicates in development is a dedup layer nobody
notices is broken.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, date, datetime, time, timedelta

from app.sources.base import RawArticle

SOURCE = "simulated"

#: (headline template, summary template, publisher). The templates take the
#: company symbol, so each ticker gets its own plausible-looking feed.
_TEMPLATES: tuple[tuple[str, str, str], ...] = (
    (
        "{symbol} beats quarterly earnings expectations and raises guidance",
        "The company reported revenue above consensus and lifted its outlook for the year.",
        "Simulated Wire",
    ),
    (
        "Regulators open an investigation into {symbol} data practices",
        "A probe has been opened into how the company handles customer data.",
        "Simulated Post",
    ),
    (
        "{symbol} announces a partnership to expand manufacturing capacity",
        "The agreement adds capacity over the next two years.",
        "Simulated Times",
    ),
    (
        "Analyst says {symbol} shares could move sharply this year",
        "An opinion piece with no new information about the business.",
        "Simulated Blog",
    ),
    (
        "{symbol} shares fall 4% in afternoon trading",
        "The move came without company-specific news.",
        "Simulated Ticker",
    ),
)


class FakeNewsSource:
    name = SOURCE

    def fetch(self, symbol: str, since: date, until: date) -> list[RawArticle]:
        articles: list[RawArticle] = []
        day = until
        for index, (title, summary, publisher) in enumerate(_TEMPLATES):
            if day < since:
                break
            published = datetime.combine(day, time(13, 30), tzinfo=UTC) + timedelta(minutes=index)
            slug = hashlib.blake2b(f"{symbol}{day}{index}".encode(), digest_size=6).hexdigest()
            url = f"https://news.invalid/{symbol.lower()}/{slug}"
            articles.append(
                RawArticle(
                    title=title.format(symbol=symbol),
                    summary=summary,
                    url=url,
                    publisher=publisher,
                    published_at=published,
                )
            )
            if index == 0:
                # The same story, syndicated: a different publisher and URL that
                # only the title fingerprint can catch.
                articles.append(
                    RawArticle(
                        title=title.format(symbol=symbol) + " - report",
                        summary=summary,
                        url=f"https://syndicated.invalid/{symbol.lower()}/{slug}",
                        publisher="Simulated Syndicate",
                        published_at=published + timedelta(minutes=5),
                    )
                )
                # And the same URL again, with tracking parameters attached.
                articles.append(
                    RawArticle(
                        title=title.format(symbol=symbol),
                        summary=summary,
                        url=f"{url}?utm_source=newsletter&utm_medium=email",
                        publisher=publisher,
                        published_at=published,
                    )
                )
            day -= timedelta(days=1)

        return sorted(articles, key=lambda a: a.published_at, reverse=True)
