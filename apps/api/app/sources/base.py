"""The news source interface.

Same shape as `providers/base.py` and `llm/base.py`: a source is a configuration
choice. Adding publisher RSS, Reddit or StockTwits is a new implementation of
this Protocol and a line in the registry, not a change to the ingest service.

Sources map their own failures onto `SourceError` so one dead feed degrades the
run instead of stopping it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol, runtime_checkable


class SourceError(Exception):
    """Any failure fetching from a source. Callers log and continue."""

    def __init__(self, source: str, message: str) -> None:
        super().__init__(f"{source}: {message}")
        self.source = source


class SourceRateLimited(SourceError):
    """The source asked us to slow down. The next cycle tries again."""


@dataclass(frozen=True)
class RawArticle:
    """One article as a source hands it over, before dedup or scoring.

    `url` and `publisher` are required, not optional: rule 4 says every ingested
    item is citable, and an item we cannot attribute is not worth storing.
    """

    title: str
    summary: str | None
    url: str
    publisher: str
    published_at: datetime


@runtime_checkable
class NewsSource(Protocol):
    name: str

    def fetch(self, symbol: str, since: date, until: date) -> list[RawArticle]:
        """Articles about `symbol` published in the window, newest first."""
        ...
