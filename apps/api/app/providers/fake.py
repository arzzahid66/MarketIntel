"""Simulated market data.

Lets the whole pipeline - ingest, cache, signals, live push - run without a
provider key, in development, tests and CI. It is never a stand-in for real
data in front of a customer: `is_simulated` is True, every row it produces is
stored with source="simulated", the UI labels it on every page, and production
refuses to boot with MARKET_DATA_PROVIDER=fake.

Deterministic: prices are a seeded random walk keyed by symbol and date, so two
processes (API and worker) and two test runs see exactly the same numbers.
During a session the live price moves minute by minute and lands exactly on the
day's close at 16:00, so the dashboard visibly ticks without ever disagreeing
with the daily bar it later becomes.
"""

from __future__ import annotations

import hashlib
import math
import random
import re
from datetime import UTC, date, timedelta
from functools import lru_cache

from app.core.clock import Clock, system_clock
from app.providers.base import (
    SIMULATED_SOURCE,
    CompanyProfile,
    DailyBar,
    Quote,
    SymbolNotFound,
)
from app.services.market_hours import (
    is_trading_day,
    market_status,
    previous_trading_day,
    session_bounds,
)

SOURCE = SIMULATED_SOURCE
SERIES_START = date(2025, 1, 2)
SERIES_END = date(2028, 12, 29)

_SYMBOL = re.compile(r"^[A-Z][A-Z.]{0,9}$")

#: Starting prices and descriptive data for the seeded universe.
_KNOWN: dict[str, tuple[float, str, str, float]] = {
    # symbol: (price at SERIES_START, name, industry, shares outstanding in billions)
    "AAPL": (185.0, "Apple Inc.", "Technology", 15.0),
    "MSFT": (370.0, "Microsoft Corporation", "Technology", 7.4),
    "GOOGL": (140.0, "Alphabet Inc. Class A", "Media", 12.3),
    "AMZN": (150.0, "Amazon.com Inc.", "Retail", 10.5),
    "NVDA": (48.0, "NVIDIA Corporation", "Semiconductors", 24.5),
    "META": (350.0, "Meta Platforms Inc.", "Media", 2.5),
    "TSLA": (240.0, "Tesla Inc.", "Automobiles", 3.2),
}


def _seed(*parts: object) -> int:
    digest = hashlib.sha256(":".join(str(p) for p in parts).encode()).digest()
    return int.from_bytes(digest[:8], "big")


@lru_cache(maxsize=64)
def _series(symbol: str) -> tuple[dict[date, DailyBar], tuple[date, ...]]:
    """Every simulated session for `symbol` between SERIES_START and SERIES_END."""
    base_price, *_ = _KNOWN.get(symbol, (50 + _seed(symbol, "base") % 450, "", "", 1.0))
    phase = (_seed(symbol, "phase") % 628) / 100.0
    base_volume = 20_000_000 + _seed(symbol, "volume") % 60_000_000

    bars: dict[date, DailyBar] = {}
    sessions: list[date] = []
    previous_close = float(base_price)
    day = SERIES_START
    index = 0
    while day <= SERIES_END:
        if is_trading_day(day):
            rng = random.Random(_seed(symbol, day.isoformat()))
            # A slow trend cycle plus noise, so signals swing between bullish and
            # bearish over weeks instead of sitting on neutral forever.
            trend = 0.0032 * math.sin(index / 13.0 + phase)
            daily_return = trend + rng.gauss(0.0002, 0.014)
            close = max(1.0, previous_close * (1.0 + daily_return))
            open_ = previous_close * (1.0 + rng.gauss(0, 0.004))
            high = max(open_, close) * (1.0 + abs(rng.gauss(0, 0.006)))
            low = min(open_, close) * (1.0 - abs(rng.gauss(0, 0.006)))
            volume = int(base_volume * math.exp(rng.gauss(0, 0.3)) * (1 + 12 * abs(daily_return)))
            bars[day] = DailyBar(
                symbol=symbol,
                session_date=day,
                open=round(open_, 2),
                high=round(high, 2),
                low=round(low, 2),
                close=round(close, 2),
                volume=volume,
                source=SOURCE,
            )
            sessions.append(day)
            previous_close = close
            index += 1
        day += timedelta(days=1)
    return bars, tuple(sessions)


class FakeProvider:
    name = SOURCE
    is_simulated = True

    def __init__(self, clock: Clock = system_clock) -> None:
        self._clock = clock

    def _check(self, symbol: str) -> None:
        if not _SYMBOL.match(symbol):
            raise SymbolNotFound(self.name, f"invalid symbol {symbol!r}")

    def _close(self, symbol: str, day: date) -> float:
        bars, _ = _series(symbol)
        bar = bars.get(day)
        if bar is None:
            raise SymbolNotFound(self.name, f"no simulated session for {symbol} on {day}")
        return bar.close

    def get_quote(self, symbol: str) -> Quote:
        self._check(symbol)
        now = self._clock()
        status = market_status(now)

        if status.is_open and status.current_session is not None:
            session = status.current_session
            bars, _ = _series(symbol)
            bar = bars[session]
            previous_close = self._close(symbol, previous_trading_day(session))
            open_utc, close_utc = session_bounds(session)
            progress = (now - open_utc) / (close_utc - open_utc)
            minute = now.replace(second=0, microsecond=0)
            wiggle = random.Random(_seed(symbol, minute.isoformat())).gauss(0, 0.0015)
            # Interpolate from the open to the close, with noise that fades out
            # so the final print equals the daily bar's close exactly.
            price = bar.open + (bar.close - bar.open) * progress
            price *= 1.0 + wiggle * (1.0 - progress)
            price = round(price, 2)
            provider_time = minute
            high = round(max(bar.open, price, bar.open + (bar.high - bar.open) * progress), 2)
            low = round(min(bar.open, price, bar.open - (bar.open - bar.low) * progress), 2)
            open_ = bar.open
        else:
            session = status.last_completed_session
            bars, _ = _series(symbol)
            bar = bars[session]
            previous_close = self._close(symbol, previous_trading_day(session))
            price, high, low, open_ = bar.close, bar.high, bar.low, bar.open
            provider_time = session_bounds(session)[1]

        change = round(price - previous_close, 2)
        return Quote(
            symbol=symbol,
            price=price,
            change=change,
            change_percent=round(change / previous_close * 100.0, 4),
            previous_close=previous_close,
            open=open_,
            high=high,
            low=low,
            provider_time=provider_time.astimezone(UTC),
            source=self.name,
        )

    def get_daily_bars(self, symbol: str, start: date, end: date) -> list[DailyBar]:
        self._check(symbol)
        last_completed = market_status(self._clock()).last_completed_session
        bars, sessions = _series(symbol)
        upper = min(end, last_completed)
        return [bars[d] for d in sessions if start <= d <= upper]

    def get_profile(self, symbol: str) -> CompanyProfile:
        self._check(symbol)
        _, name, industry, shares_billions = _KNOWN.get(symbol, (0, symbol, None, 1.0))
        price = self.get_quote(symbol).price
        return CompanyProfile(
            symbol=symbol,
            name=name or symbol,
            exchange="NASDAQ",
            industry=industry,
            market_cap=round(price * shares_billions * 1_000_000_000, 0),
            currency="USD",
            source=self.name,
        )
