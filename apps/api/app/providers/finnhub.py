"""Finnhub implementation.

Free tier: real-time US quotes, company profiles and news at 60 calls/minute.
Daily candles (/stock/candle) are a paid endpoint; on the free tier they return
403, which surfaces as ProviderAccessDenied. The registry routes daily bars to
Twelve Data when that key is configured.

The key goes in the X-Finnhub-Token header, never the query string, so it cannot
leak into access logs, proxies or error messages.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from typing import Any

import httpx

from app.providers.base import (
    CompanyProfile,
    DailyBar,
    ProviderAccessDenied,
    ProviderError,
    ProviderRateLimited,
    Quote,
    SymbolNotFound,
)
from app.services.rate_limit import TokenBucket

BASE_URL = "https://finnhub.io/api/v1"


class FinnhubProvider:
    name = "finnhub"
    is_simulated = False

    def __init__(
        self,
        api_key: str,
        bucket: TokenBucket,
        client: httpx.Client | None = None,
        timeout: float = 8.0,
    ) -> None:
        if not api_key:
            raise ValueError("Finnhub requires an API key")
        self._bucket = bucket
        self._client = client or httpx.Client(base_url=BASE_URL, timeout=timeout)
        self._headers = {"X-Finnhub-Token": api_key, "Accept": "application/json"}

    def _get(self, path: str, params: dict[str, Any]) -> Any:
        self._bucket.acquire()
        try:
            response = self._client.get(path, params=params, headers=self._headers)
        except httpx.HTTPError as exc:
            raise ProviderError(
                self.name, f"network error on {path}: {type(exc).__name__}"
            ) from exc

        if response.status_code == 429:
            raise ProviderRateLimited(self.name, f"rate limited on {path}")
        if response.status_code in (401, 403):
            raise ProviderAccessDenied(
                self.name, f"{response.status_code} on {path} (bad key or not in plan)"
            )
        if response.status_code >= 400:
            raise ProviderError(self.name, f"HTTP {response.status_code} on {path}")
        try:
            return response.json()
        except ValueError as exc:
            raise ProviderError(self.name, f"non-JSON response on {path}") from exc

    def get_quote(self, symbol: str) -> Quote:
        data = self._get("/quote", {"symbol": symbol})
        price = _num(data.get("c"))
        # Finnhub answers an unknown symbol with 200 and a body of zeros.
        if not price:
            raise SymbolNotFound(self.name, f"no quote for {symbol}")
        timestamp = data.get("t")
        return Quote(
            symbol=symbol,
            price=price,
            change=_num(data.get("d")),
            change_percent=_num(data.get("dp")),
            previous_close=_num(data.get("pc")) or None,
            open=_num(data.get("o")) or None,
            high=_num(data.get("h")) or None,
            low=_num(data.get("l")) or None,
            provider_time=datetime.fromtimestamp(timestamp, UTC) if timestamp else None,
            source=self.name,
        )

    def get_daily_bars(self, symbol: str, start: date, end: date) -> list[DailyBar]:
        start_ts = int(datetime.combine(start, time.min, tzinfo=UTC).timestamp())
        end_ts = int(datetime.combine(end + timedelta(days=1), time.min, tzinfo=UTC).timestamp())
        data = self._get(
            "/stock/candle",
            {"symbol": symbol, "resolution": "D", "from": start_ts, "to": end_ts},
        )
        if data.get("s") == "no_data":
            return []
        if data.get("s") != "ok":
            raise ProviderError(self.name, f"unexpected candle status {data.get('s')!r}")

        bars = [
            DailyBar(
                symbol=symbol,
                session_date=datetime.fromtimestamp(t, UTC).date(),
                open=float(o),
                high=float(h),
                low=float(lo),
                close=float(c),
                volume=int(v),
                source=self.name,
            )
            for t, o, h, lo, c, v in zip(
                data["t"], data["o"], data["h"], data["l"], data["c"], data["v"], strict=True
            )
        ]
        return sorted((b for b in bars if start <= b.session_date <= end), key=_by_date)

    def get_profile(self, symbol: str) -> CompanyProfile:
        data = self._get("/stock/profile2", {"symbol": symbol})
        if not data:
            raise SymbolNotFound(self.name, f"no profile for {symbol}")
        market_cap_millions = _num(data.get("marketCapitalization"))
        return CompanyProfile(
            symbol=symbol,
            name=data.get("name") or None,
            exchange=data.get("exchange") or None,
            industry=data.get("finnhubIndustry") or None,
            market_cap=market_cap_millions * 1_000_000 if market_cap_millions else None,
            currency=data.get("currency") or None,
            source=self.name,
        )


def _num(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _by_date(bar: DailyBar) -> date:
    return bar.session_date
