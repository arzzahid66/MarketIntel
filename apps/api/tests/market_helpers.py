"""Fixed instants, instrumented providers and data loaders for the market tests."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime

from sqlalchemy.orm import Session

from app.core.clock import fixed_clock
from app.core.redis import get_redis
from app.providers.base import CompanyProfile, DailyBar, ProviderError, Quote
from app.providers.fake import FakeProvider
from app.services import market_data as md

# 2026-09-14 is a Monday. Summer, so New York is UTC-4.
MONDAY_NOON_ET = datetime(2026, 9, 14, 16, 0, tzinfo=UTC)
MONDAY_PRE_MARKET_ET = datetime(2026, 9, 14, 12, 0, tzinfo=UTC)  # 08:00 ET
MONDAY_AFTER_CLOSE_ET = datetime(2026, 9, 14, 21, 0, tzinfo=UTC)  # 17:00 ET
SATURDAY_NOON_ET = datetime(2026, 9, 12, 16, 0, tzinfo=UTC)
FRIDAY = date(2026, 9, 11)


@dataclass
class SpyProvider:
    """Wraps the simulator and records every call. `fail` makes every call raise."""

    now: datetime
    fail: bool = False
    fail_symbols: set[str] = field(default_factory=set)
    calls: list[tuple[str, str]] = field(default_factory=list)

    name = "simulated"
    is_simulated = True

    def __post_init__(self) -> None:
        self._inner = FakeProvider(fixed_clock(self.now))

    def _guard(self, method: str, symbol: str) -> None:
        self.calls.append((method, symbol))
        if self.fail or symbol in self.fail_symbols:
            raise ProviderError(self.name, f"simulated outage for {symbol}")

    def get_quote(self, symbol: str) -> Quote:
        self._guard("quote", symbol)
        return self._inner.get_quote(symbol)

    def get_daily_bars(self, symbol: str, start: date, end: date) -> list[DailyBar]:
        self._guard("bars", symbol)
        return self._inner.get_daily_bars(symbol, start, end)

    def get_profile(self, symbol: str) -> CompanyProfile:
        self._guard("profile", symbol)
        return self._inner.get_profile(symbol)

    def quote_calls(self) -> int:
        return sum(1 for method, _ in self.calls if method == "quote")


def populate(db: Session, now: datetime, quotes_at: datetime | None = None) -> None:
    """Bars, quotes and signals as the worker would have left them at `now`.

    `quotes_at` fetches quotes at an earlier instant, to create stale data.
    """
    tickers = md.big7_tickers(db)
    client = get_redis()
    provider = FakeProvider(fixed_clock(now))
    md.ingest_daily_bars(db, provider, tickers, now)
    quote_time = quotes_at or now
    md.ingest_quotes(db, FakeProvider(fixed_clock(quote_time)), tickers, quote_time, client)
    md.compute_signals(db, tickers, now, client)
