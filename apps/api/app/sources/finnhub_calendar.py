"""Finnhub earnings calendar.

Verified on the free tier on 2026-10-26: `/calendar/earnings` returns 200 with
the whole forward market calendar (1,500 rows for a two-week window), while
`/calendar/economic` returns 403. See `calendar_base.py` for why that decides
what this surface shows.

Shares the `finnhub` token bucket with the quote provider and the news source,
because all three spend one per-minute budget against one key.

**The endpoint silently truncates, and it truncates the wrong end.** Measured on
2026-10-26: a 3-day window returned 784 rows spanning exactly those 3 days, but
a 38-day window returned exactly 1,500 rows spanning only the *last* 16 days,
and a 105-day window returned exactly 1,500 spanning only the last 74. There is
no flag, no error and no `hasMore` in the body - the nearest dates, which are
the ones a reader actually cares about, are the ones dropped. So this source
never issues one wide request: it walks the window in `CHUNK_DAYS` slices and
merges, and shouts if a slice still comes back at the cap.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import httpx

from app.core.logging import get_logger
from app.services.rate_limit import TokenBucket
from app.sources.calendar_base import RawEarnings, SourceError, SourceRateLimited

log = get_logger("sources.finnhub_calendar")

BASE_URL = "https://finnhub.io/api/v1"

#: Rows a single response will return before it starts dropping the earliest
#: dates. Measured, not documented by the provider - two unrelated windows both
#: came back at exactly this number.
RESPONSE_CAP = 1500

#: Days per request. The busiest three days of an earnings season measured 784
#: rows, so five days leaves real headroom under RESPONSE_CAP. Lower it if
#: `calendar_window_truncated` ever appears in the logs.
CHUNK_DAYS = 5


class FinnhubEarningsCalendar:
    name = "finnhub"

    def __init__(
        self,
        api_key: str,
        bucket: TokenBucket,
        client: httpx.Client | None = None,
        timeout: float = 8.0,
    ) -> None:
        if not api_key:
            raise ValueError("Finnhub earnings calendar requires an API key")
        self._bucket = bucket
        self._client = client or httpx.Client(base_url=BASE_URL, timeout=timeout)
        self._headers = {"X-Finnhub-Token": api_key, "Accept": "application/json"}

    def fetch(self, since: date, until: date) -> list[RawEarnings]:
        """Walk the window in slices and merge, because one wide request lies.

        Deduplicated on `(symbol, session_date)` - the table's own unique key -
        so overlapping slices cannot double-count an event.
        """
        if until < since:
            return []

        merged: dict[tuple[str, date], RawEarnings] = {}
        start = since
        while start <= until:
            stop = min(start + timedelta(days=CHUNK_DAYS - 1), until)
            for event in self._fetch_window(start, stop):
                merged[(event.symbol, event.session_date)] = event
            start = stop + timedelta(days=1)

        return sorted(merged.values(), key=lambda e: (e.session_date, e.symbol))

    def _fetch_window(self, since: date, until: date) -> list[RawEarnings]:
        self._bucket.acquire()
        params = {"from": since.isoformat(), "to": until.isoformat()}
        try:
            response = self._client.get("/calendar/earnings", params=params, headers=self._headers)
        except httpx.HTTPError as exc:
            raise SourceError(self.name, f"network error: {type(exc).__name__}") from exc

        if response.status_code == 429:
            raise SourceRateLimited(self.name, "rate limited")
        if response.status_code in (401, 403):
            raise SourceError(self.name, f"{response.status_code} (bad key or not in plan)")
        if response.status_code >= 400:
            raise SourceError(self.name, f"HTTP {response.status_code}")

        try:
            payload = response.json()
        except ValueError as exc:
            raise SourceError(self.name, "non-JSON response") from exc
        if not isinstance(payload, dict):
            raise SourceError(self.name, f"expected an object, got {type(payload).__name__}")

        rows = payload.get("earningsCalendar")
        if rows is None:
            # An empty window is a legitimate answer, not a failure.
            return []
        if not isinstance(rows, list):
            raise SourceError(self.name, "earningsCalendar was not a list")

        if len(rows) >= RESPONSE_CAP:
            # The response was truncated, so this slice is missing its earliest
            # dates. Loud rather than silent: the fix is a smaller CHUNK_DAYS.
            log.warning(
                "calendar_window_truncated",
                source=self.name,
                requested_from=since.isoformat(),
                requested_to=until.isoformat(),
                rows=len(rows),
                cap=RESPONSE_CAP,
            )

        events = [e for e in (_event(row) for row in rows) if e is not None]
        return sorted(events, key=lambda e: (e.session_date, e.symbol))


def _number(value: Any) -> float | None:
    """A float, or None. Rejects bools, which are ints in Python but not data."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


def _integer(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return int(value)


def _event(row: Any) -> RawEarnings | None:
    """One Finnhub row, or None when it has no symbol and date to key on."""
    if not isinstance(row, dict):
        return None
    symbol = (row.get("symbol") or "").strip().upper()
    raw_date = (row.get("date") or "").strip()
    if not symbol or not raw_date:
        return None
    try:
        session_date = date.fromisoformat(raw_date)
    except ValueError:
        return None

    timing = (row.get("hour") or "").strip().lower()[:8]

    return RawEarnings(
        symbol=symbol,
        session_date=session_date,
        timing=timing,
        fiscal_quarter=_integer(row.get("quarter")),
        fiscal_year=_integer(row.get("year")),
        eps_estimate=_number(row.get("epsEstimate")),
        eps_actual=_number(row.get("epsActual")),
        revenue_estimate=_number(row.get("revenueEstimate")),
        revenue_actual=_number(row.get("revenueActual")),
    )
