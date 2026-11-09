"""The market data provider interface.

Everything above this layer speaks `Quote`, `DailyBar` and `CompanyProfile`.
Swapping Finnhub for Polygon is a new implementation of this Protocol and a line
in the registry - not a rewrite (build plan, Phase 2).

Providers are called only by the worker and by the API's rate-limited background
revalidation. Never from a request path that a page waits on, and never from the
browser.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol, runtime_checkable

#: The `source` every simulated row is stored with. Rows outlive the provider
#: that made them: swapping a key to a real provider does not turn yesterday's
#: simulated bars real, so the dashboard checks the row, not just the provider.
SIMULATED_SOURCE = "simulated"


@dataclass(frozen=True)
class Quote:
    symbol: str
    price: float
    change: float | None
    change_percent: float | None
    previous_close: float | None
    open: float | None
    high: float | None
    low: float | None
    #: When the provider says the price was observed. Not when we fetched it.
    provider_time: datetime | None
    source: str


@dataclass(frozen=True)
class DailyBar:
    symbol: str
    session_date: date
    open: float
    high: float
    low: float
    close: float
    volume: int
    source: str


@dataclass(frozen=True)
class CompanyProfile:
    symbol: str
    name: str | None
    exchange: str | None
    industry: str | None
    #: Whole US dollars. Finnhub reports millions; implementations convert.
    market_cap: float | None
    currency: str | None
    source: str


class ProviderError(Exception):
    """Any failure talking to a provider. Callers degrade; they never crash a page."""

    def __init__(self, provider: str, message: str) -> None:
        super().__init__(f"{provider}: {message}")
        self.provider = provider


class ProviderRateLimited(ProviderError):
    """The provider returned 429 or its body-level equivalent."""


class ProviderAccessDenied(ProviderError):
    """Bad key, or the endpoint is not included in the current plan."""


class SymbolNotFound(ProviderError):
    """The provider has no data for this symbol."""


@runtime_checkable
class MarketDataProvider(Protocol):
    # Declared read-only, so an implementation may compute them. `RoutedProvider`
    # derives both from the providers it wraps ("finnhub+twelvedata"); a plain
    # class attribute satisfies a read-only property just as well.
    @property
    def name(self) -> str:
        """Stored on every row this provider produces, so data is attributable."""
        ...

    @property
    def is_simulated(self) -> bool:
        """True only for the built-in simulator. The UI must say so on every page."""
        ...

    def get_quote(self, symbol: str) -> Quote: ...

    def get_daily_bars(self, symbol: str, start: date, end: date) -> list[DailyBar]:
        """Completed sessions in [start, end], oldest first."""
        ...

    def get_profile(self, symbol: str) -> CompanyProfile: ...
