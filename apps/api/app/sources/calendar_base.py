"""The earnings-calendar source interface.

Same shape as `sources/base.py`, `providers/base.py` and `llm/base.py`: the
source is a configuration choice, and swapping it is a new implementation plus a
line in the registry.

**Why earnings and not macro.** The build plan asks for an "economic calendar".
Measured against a live free-tier key on 2026-10-26, Finnhub returns **403** on
`/calendar/economic` and **200** on `/calendar/earnings`. Macro prints therefore
need a source the client has not chosen yet (section 6 lists Investing.com, FMP
and Trading Economics). Rather than ship an empty panel or quietly relabel
earnings as macro, this interface is named for what it actually returns, and a
macro source becomes a sibling Protocol when a key exists.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Protocol, runtime_checkable

from app.sources.base import SourceError, SourceRateLimited

__all__ = [
    "EarningsCalendarSource",
    "RawEarnings",
    "SourceError",
    "SourceRateLimited",
]


@dataclass(frozen=True)
class RawEarnings:
    """One scheduled or reported result, as a source hands it over.

    Everything but `symbol` and `session_date` is optional: a date eight weeks
    out carries no estimate yet, and an estimate is not a reason to withhold the
    date. The two required fields are exactly the unique key we upsert on.
    """

    symbol: str
    session_date: date
    #: "bmo", "amc", or "" when the source does not say. Kept as the source's
    #: own token so a new one cannot break ingest.
    timing: str
    fiscal_quarter: int | None
    fiscal_year: int | None
    eps_estimate: float | None
    eps_actual: float | None
    revenue_estimate: float | None
    revenue_actual: float | None


@runtime_checkable
class EarningsCalendarSource(Protocol):
    name: str

    def fetch(self, since: date, until: date) -> list[RawEarnings]:
        """Every event in [since, until]. Not filtered to our universe.

        The provider returns the whole market, and filtering is the caller's
        job: a symbol we do not follow today may be followed tomorrow, and one
        request for the market costs the same as one request for a symbol.
        """
        ...
