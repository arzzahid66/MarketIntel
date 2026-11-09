"""Twelve Data implementation - daily bars only.

Used because Finnhub's free tier does not serve daily candles. Free tier: 8
calls/minute, 800/day, which is plenty for one backfill per symbol per day.

Twelve Data often reports errors with HTTP 200 and `"status": "error"` in the
body, so status is checked in both places. The key travels in the Authorization
header rather than the `apikey` query parameter.
"""

from __future__ import annotations

from datetime import date, timedelta
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

BASE_URL = "https://api.twelvedata.com"


class TwelveDataProvider:
    name = "twelvedata"
    is_simulated = False

    def __init__(
        self,
        api_key: str,
        bucket: TokenBucket,
        client: httpx.Client | None = None,
        timeout: float = 8.0,
    ) -> None:
        if not api_key:
            raise ValueError("Twelve Data requires an API key")
        self._bucket = bucket
        self._client = client or httpx.Client(base_url=BASE_URL, timeout=timeout)
        self._headers = {"Authorization": f"apikey {api_key}", "Accept": "application/json"}

    def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        self._bucket.acquire()
        try:
            response = self._client.get(path, params=params, headers=self._headers)
        except httpx.HTTPError as exc:
            raise ProviderError(
                self.name, f"network error on {path}: {type(exc).__name__}"
            ) from exc

        try:
            data = response.json()
        except ValueError as exc:
            raise ProviderError(self.name, f"HTTP {response.status_code}, non-JSON body") from exc

        code = response.status_code
        if isinstance(data, dict) and data.get("status") == "error":
            code = int(data.get("code") or code or 500)

        if code == 429:
            raise ProviderRateLimited(self.name, "rate limited")
        if code in (401, 403):
            raise ProviderAccessDenied(self.name, f"{code} (bad key or not in plan)")
        if code in (400, 404):
            raise SymbolNotFound(self.name, str(data.get("message", "symbol not found")))
        if code >= 400:
            raise ProviderError(self.name, f"HTTP {code}")
        return data

    def get_daily_bars(self, symbol: str, start: date, end: date) -> list[DailyBar]:
        data = self._get(
            "/time_series",
            {
                "symbol": symbol,
                "interval": "1day",
                "start_date": start.isoformat(),
                # end_date is exclusive on some plans; ask for a day more and filter.
                "end_date": (end + timedelta(days=1)).isoformat(),
                "order": "ASC",
                "timezone": "America/New_York",
            },
        )
        bars: list[DailyBar] = []
        for row in data.get("values") or []:
            session = date.fromisoformat(str(row["datetime"])[:10])
            if not start <= session <= end:
                continue
            bars.append(
                DailyBar(
                    symbol=symbol,
                    session_date=session,
                    open=float(row["open"]),
                    high=float(row["high"]),
                    low=float(row["low"]),
                    close=float(row["close"]),
                    volume=int(float(row.get("volume") or 0)),
                    source=self.name,
                )
            )
        return sorted(bars, key=lambda b: b.session_date)

    def get_quote(self, symbol: str) -> Quote:
        raise ProviderAccessDenied(self.name, "quotes are routed to Finnhub")

    def get_profile(self, symbol: str) -> CompanyProfile:
        raise ProviderAccessDenied(self.name, "profiles are routed to Finnhub")
