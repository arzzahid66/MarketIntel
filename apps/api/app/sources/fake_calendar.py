"""A deterministic earnings calendar for development, tests and CI.

Places one event per symbol on a date derived from the symbol itself, so the
calendar surface renders with no key and no network call, and two runs produce
exactly the same rows.

Some rows carry a reported actual and some carry only an estimate. That is the
distinction the UI has to render, so development data has to contain both - a
calendar stub where every row looks identical hides the one case that is easy to
get wrong.

It never reads the clock. The caller builds the window around `now`, so the
window's own midpoint stands in for today: rows before it are treated as
reported, rows after it as scheduled. That keeps the stub pure and deterministic
while still producing both shapes.
"""

from __future__ import annotations

import hashlib
from datetime import date, timedelta

from app.sources.calendar_base import RawEarnings

SOURCE = "simulated"

#: The universe the stub invents a calendar for. Enough names to fill a panel
#: without pretending to be the whole market.
_SYMBOLS: tuple[str, ...] = (
    "AAPL",
    "MSFT",
    "GOOGL",
    "AMZN",
    "NVDA",
    "META",
    "TSLA",
    "JPM",
    "XOM",
    "JNJ",
    "WMT",
    "PG",
)

_TIMINGS = ("bmo", "amc", "")


def _spread(symbol: str, modulus: int) -> int:
    """A stable number per symbol, so the same symbol lands on the same date."""
    digest = hashlib.sha256(symbol.encode()).digest()
    return digest[0] % modulus


class FakeEarningsCalendar:
    name = SOURCE

    def fetch(self, since: date, until: date) -> list[RawEarnings]:
        if until < since:
            return []
        span = (until - since).days + 1
        # Stands in for "today" without reading a clock - see the module
        # docstring. The caller centres the window on now.
        midpoint = since + timedelta(days=span // 2)

        events: list[RawEarnings] = []
        for symbol in _SYMBOLS:
            session_date = since + timedelta(days=_spread(symbol, span))
            reported = session_date < midpoint
            estimate = round(0.5 + _spread(symbol, 400) / 100, 2)
            events.append(
                RawEarnings(
                    symbol=symbol,
                    session_date=session_date,
                    timing=_TIMINGS[_spread(symbol, len(_TIMINGS))],
                    fiscal_quarter=1 + _spread(symbol, 4),
                    fiscal_year=session_date.year,
                    eps_estimate=estimate,
                    # Reported events beat or miss by a stable margin; scheduled
                    # ones have no actual at all.
                    eps_actual=round(estimate + (_spread(symbol, 21) - 10) / 100, 2)
                    if reported
                    else None,
                    revenue_estimate=float(1_000_000_000 + _spread(symbol, 50) * 10_000_000),
                    revenue_actual=float(1_000_000_000 + _spread(symbol, 60) * 10_000_000)
                    if reported
                    else None,
                )
            )
        return sorted(events, key=lambda e: (e.session_date, e.symbol))
