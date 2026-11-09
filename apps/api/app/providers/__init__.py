"""Provider registry.

One function decides where market data comes from, from configuration alone:

    MARKET_DATA_PROVIDER=fake     -> simulated everything
    MARKET_DATA_PROVIDER=finnhub  -> Finnhub (boot fails without FINNHUB_API_KEY)
    MARKET_DATA_PROVIDER=auto     -> Finnhub if FINNHUB_API_KEY is set, else simulated

With Finnhub, daily bars come from Twelve Data when TWELVEDATA_API_KEY is set,
because Finnhub's free tier does not include daily candles.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from functools import lru_cache

from app.core.config import Settings, settings
from app.core.redis import get_redis
from app.providers.base import (
    CompanyProfile,
    DailyBar,
    MarketDataProvider,
    ProviderAccessDenied,
    ProviderError,
    ProviderRateLimited,
    Quote,
    SymbolNotFound,
)
from app.providers.fake import FakeProvider
from app.providers.finnhub import FinnhubProvider
from app.providers.twelvedata import TwelveDataProvider
from app.services.rate_limit import TokenBucket


@dataclass
class RoutedProvider:
    """Quotes and profiles from one provider, daily bars from another."""

    quotes: MarketDataProvider
    bars: MarketDataProvider

    @property
    def name(self) -> str:
        if self.quotes.name == self.bars.name:
            return self.quotes.name
        return f"{self.quotes.name}+{self.bars.name}"

    @property
    def is_simulated(self) -> bool:
        return self.quotes.is_simulated or self.bars.is_simulated

    def get_quote(self, symbol: str) -> Quote:
        return self.quotes.get_quote(symbol)

    def get_daily_bars(self, symbol: str, start: date, end: date) -> list[DailyBar]:
        return self.bars.get_daily_bars(symbol, start, end)

    def get_profile(self, symbol: str) -> CompanyProfile:
        return self.quotes.get_profile(symbol)


def build_provider(config: Settings) -> MarketDataProvider:
    finnhub_key = config.finnhub_api_key.get_secret_value()
    twelvedata_key = config.twelvedata_api_key.get_secret_value()

    mode = config.market_data_provider
    if mode == "fake" or (mode == "auto" and not finnhub_key):
        return FakeProvider()
    if not finnhub_key:
        raise RuntimeError("MARKET_DATA_PROVIDER=finnhub but FINNHUB_API_KEY is not set")

    client = get_redis()
    finnhub = FinnhubProvider(
        finnhub_key,
        TokenBucket("finnhub", config.finnhub_calls_per_minute, client=client),
        timeout=config.provider_timeout_seconds,
    )
    if not twelvedata_key:
        return finnhub
    twelvedata = TwelveDataProvider(
        twelvedata_key,
        TokenBucket("twelvedata", config.twelvedata_calls_per_minute, capacity=1, client=client),
        timeout=config.provider_timeout_seconds,
    )
    return RoutedProvider(quotes=finnhub, bars=twelvedata)


@lru_cache(maxsize=1)
def get_market_data_provider() -> MarketDataProvider:
    return build_provider(settings)


__all__ = [
    "CompanyProfile",
    "DailyBar",
    "MarketDataProvider",
    "ProviderAccessDenied",
    "ProviderError",
    "ProviderRateLimited",
    "Quote",
    "RoutedProvider",
    "SymbolNotFound",
    "build_provider",
    "get_market_data_provider",
]
