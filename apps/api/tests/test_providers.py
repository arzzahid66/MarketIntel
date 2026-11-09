"""Provider implementations, tested against recorded-shape HTTP responses.

No test here touches the network. `httpx.MockTransport` stands in for Finnhub
and Twelve Data, so the parsing and error mapping are exercised exactly as they
run in production.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime

import httpx
import pytest

from app.core.clock import fixed_clock
from app.core.config import Settings
from app.providers import RoutedProvider, build_provider
from app.providers.base import (
    MarketDataProvider,
    ProviderAccessDenied,
    ProviderError,
    ProviderRateLimited,
    SymbolNotFound,
)
from app.providers.fake import FakeProvider
from app.providers.finnhub import BASE_URL as FINNHUB_URL
from app.providers.finnhub import FinnhubProvider
from app.providers.twelvedata import BASE_URL as TWELVEDATA_URL
from app.providers.twelvedata import TwelveDataProvider
from app.services.rate_limit import TokenBucket
from tests.market_helpers import FRIDAY, MONDAY_NOON_ET, SATURDAY_NOON_ET

Handler = Callable[[httpx.Request], httpx.Response]


def unlimited() -> TokenBucket:
    return TokenBucket("test", per_minute=60_000, capacity=1_000, client=None)


def finnhub(handler: Handler) -> FinnhubProvider:
    client = httpx.Client(base_url=FINNHUB_URL, transport=httpx.MockTransport(handler))
    return FinnhubProvider("finnhub-test-key", unlimited(), client=client)


def twelvedata(handler: Handler) -> TwelveDataProvider:
    client = httpx.Client(base_url=TWELVEDATA_URL, transport=httpx.MockTransport(handler))
    return TwelveDataProvider("td-test-key", unlimited(), client=client)


# --------------------------------------------------------------------------
# Finnhub
# --------------------------------------------------------------------------


def test_finnhub_quote_is_parsed_and_the_key_stays_out_of_the_url() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            json={
                "c": 231.5,
                "d": 1.25,
                "dp": 0.5429,
                "h": 232.1,
                "l": 229.0,
                "o": 230.0,
                "pc": 230.25,
                "t": 1789920000,
            },
        )

    quote = finnhub(handler).get_quote("AAPL")
    assert quote.price == 231.5
    assert quote.change_percent == pytest.approx(0.5429)
    assert quote.previous_close == 230.25
    assert quote.provider_time == datetime.fromtimestamp(1789920000, UTC)
    assert quote.source == "finnhub"

    request = seen[0]
    assert request.url.path.endswith("/quote")
    assert request.headers["X-Finnhub-Token"] == "finnhub-test-key"
    assert "finnhub-test-key" not in str(request.url)


def test_finnhub_zero_body_means_unknown_symbol() -> None:
    provider = finnhub(lambda r: httpx.Response(200, json={"c": 0, "d": None, "dp": None, "t": 0}))
    with pytest.raises(SymbolNotFound):
        provider.get_quote("NOPE")


@pytest.mark.parametrize(
    ("status", "error"),
    [
        (429, ProviderRateLimited),
        (401, ProviderAccessDenied),
        (403, ProviderAccessDenied),
        (500, ProviderError),
    ],
)
def test_finnhub_http_errors_map_to_provider_errors(status: int, error: type[Exception]) -> None:
    provider = finnhub(lambda r: httpx.Response(status, json={"error": "nope"}))
    with pytest.raises(error):
        provider.get_quote("AAPL")


def test_finnhub_network_failure_is_a_provider_error_not_a_crash() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("timed out", request=request)

    with pytest.raises(ProviderError):
        finnhub(handler).get_quote("AAPL")


def test_finnhub_candles_are_sorted_and_filtered_to_the_range() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "s": "ok",
                # Deliberately out of order, with one day outside the range.
                "t": [1789084800, 1788912000, 1788825600],  # 09-11, 09-09, 09-08
                "o": [3, 2, 1],
                "h": [3, 2, 1],
                "l": [3, 2, 1],
                "c": [3, 2, 1],
                "v": [300, 200, 100],
            },
        )

    bars = finnhub(handler).get_daily_bars("AAPL", date(2026, 9, 9), date(2026, 9, 11))
    assert [b.session_date for b in bars] == [date(2026, 9, 9), date(2026, 9, 11)]
    assert [b.close for b in bars] == [2.0, 3.0]


def test_finnhub_candles_no_data_is_empty_not_an_error() -> None:
    provider = finnhub(lambda r: httpx.Response(200, json={"s": "no_data"}))
    assert provider.get_daily_bars("AAPL", date(2026, 9, 1), date(2026, 9, 11)) == []


def test_finnhub_profile_converts_market_cap_from_millions() -> None:
    provider = finnhub(
        lambda r: httpx.Response(
            200,
            json={
                "name": "Apple Inc",
                "exchange": "NASDAQ NMS - GLOBAL MARKET",
                "finnhubIndustry": "Technology",
                "marketCapitalization": 3500000,
                "currency": "USD",
            },
        )
    )
    profile = provider.get_profile("AAPL")
    assert profile.market_cap == 3_500_000_000_000
    assert profile.industry == "Technology"


# --------------------------------------------------------------------------
# Twelve Data
# --------------------------------------------------------------------------


def test_twelvedata_bars_parse_strings_and_filter_the_padded_end_date() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            json={
                "meta": {"symbol": "AAPL", "interval": "1day"},
                "values": [
                    {
                        "datetime": "2026-09-12",
                        "open": "9",
                        "high": "9",
                        "low": "9",
                        "close": "9",
                        "volume": "9",
                    },
                    {
                        "datetime": "2026-09-10",
                        "open": "1.5",
                        "high": "2.5",
                        "low": "1.0",
                        "close": "2.0",
                        "volume": "12345",
                    },
                    {
                        "datetime": "2026-09-11",
                        "open": "2.0",
                        "high": "3.0",
                        "low": "1.5",
                        "close": "2.5",
                        "volume": "23456",
                    },
                ],
                "status": "ok",
            },
        )

    bars = twelvedata(handler).get_daily_bars("AAPL", date(2026, 9, 10), date(2026, 9, 11))
    assert [(b.session_date, b.close, b.volume) for b in bars] == [
        (date(2026, 9, 10), 2.0, 12345),
        (date(2026, 9, 11), 2.5, 23456),
    ]
    assert seen[0].headers["Authorization"] == "apikey td-test-key"
    assert "td-test-key" not in str(seen[0].url)


@pytest.mark.parametrize(
    ("code", "error"),
    [(429, ProviderRateLimited), (401, ProviderAccessDenied), (400, SymbolNotFound)],
)
def test_twelvedata_body_level_errors_are_detected_even_with_http_200(
    code: int, error: type[Exception]
) -> None:
    provider = twelvedata(
        lambda r: httpx.Response(200, json={"code": code, "message": "x", "status": "error"})
    )
    with pytest.raises(error):
        provider.get_daily_bars("AAPL", date(2026, 9, 1), date(2026, 9, 11))


# --------------------------------------------------------------------------
# Simulator
# --------------------------------------------------------------------------


def test_simulator_is_deterministic_across_instances() -> None:
    a = FakeProvider(fixed_clock(MONDAY_NOON_ET)).get_quote("AAPL")
    b = FakeProvider(fixed_clock(MONDAY_NOON_ET)).get_quote("AAPL")
    assert a == b


def test_simulator_never_returns_a_bar_for_an_unfinished_session() -> None:
    provider = FakeProvider(fixed_clock(MONDAY_NOON_ET))
    bars = provider.get_daily_bars("MSFT", date(2026, 9, 1), date(2026, 9, 14))
    assert bars[-1].session_date == FRIDAY
    assert all(b.session_date.weekday() < 5 for b in bars)
    assert date(2026, 9, 7) not in {b.session_date for b in bars}  # Labor Day


def test_simulator_quote_on_a_weekend_is_fridays_close() -> None:
    provider = FakeProvider(fixed_clock(SATURDAY_NOON_ET))
    quote = provider.get_quote("NVDA")
    friday_bar = provider.get_daily_bars("NVDA", FRIDAY, FRIDAY)[0]
    assert quote.price == friday_bar.close


def test_simulator_final_intraday_print_equals_the_daily_close() -> None:
    """The live price and the bar it becomes must agree, or the table jumps at 16:00."""
    just_before_close = datetime(2026, 9, 14, 19, 59, 59, tzinfo=UTC)
    live = FakeProvider(fixed_clock(just_before_close)).get_quote("TSLA")
    after = FakeProvider(fixed_clock(datetime(2026, 9, 14, 21, 0, tzinfo=UTC)))
    bar = after.get_daily_bars("TSLA", date(2026, 9, 14), date(2026, 9, 14))[0]
    assert live.price == pytest.approx(bar.close, rel=0.002)


def test_simulator_rejects_garbage_symbols() -> None:
    with pytest.raises(SymbolNotFound):
        FakeProvider().get_quote("not a symbol")


# --------------------------------------------------------------------------
# Registry
# --------------------------------------------------------------------------


def settings_with(**overrides: object) -> Settings:
    base = {"redis_url": "", "finnhub_api_key": "", "twelvedata_api_key": ""}
    return Settings(**{**base, **overrides})


def test_auto_without_a_key_is_simulated() -> None:
    provider: MarketDataProvider = build_provider(settings_with(market_data_provider="auto"))
    assert provider.is_simulated


def test_auto_with_a_finnhub_key_is_real() -> None:
    provider = build_provider(settings_with(market_data_provider="auto", finnhub_api_key="k"))
    assert isinstance(provider, FinnhubProvider)
    assert not provider.is_simulated


def test_finnhub_plus_twelvedata_routes_bars_separately() -> None:
    provider = build_provider(
        settings_with(market_data_provider="auto", finnhub_api_key="k", twelvedata_api_key="t")
    )
    assert isinstance(provider, RoutedProvider)
    assert provider.name == "finnhub+twelvedata"
    assert isinstance(provider.bars, TwelveDataProvider)


def test_explicit_finnhub_without_a_key_fails_loudly() -> None:
    with pytest.raises(RuntimeError):
        build_provider(settings_with(market_data_provider="finnhub"))
