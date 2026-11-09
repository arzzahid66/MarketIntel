"""US equity market hours (NYSE / NASDAQ regular session).

Outside regular hours the dashboard shows the last close rather than a stale
"live" number (Phase 2 requirement). Everything here takes an explicit `now`
so it is pure and testable; nothing reads the wall clock implicitly.

Holidays are data. NYSE publishes its calendar a few years ahead - add the next
year's rows when they are announced. `calendar_covers()` lets the readiness
probe flag a calendar that has run out.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

EXCHANGE_TZ = ZoneInfo("America/New_York")

REGULAR_OPEN = time(9, 30)
REGULAR_CLOSE = time(16, 0)
EARLY_CLOSE = time(13, 0)
PRE_MARKET_OPEN = time(4, 0)
POST_MARKET_CLOSE = time(20, 0)

#: Full-day closures, from the NYSE holiday calendar.
HOLIDAYS: dict[date, str] = {
    # 2026
    date(2026, 1, 1): "New Year's Day",
    date(2026, 1, 19): "Martin Luther King Jr. Day",
    date(2026, 2, 16): "Washington's Birthday",
    date(2026, 4, 3): "Good Friday",
    date(2026, 5, 25): "Memorial Day",
    date(2026, 6, 19): "Juneteenth",
    date(2026, 7, 3): "Independence Day (observed)",
    date(2026, 9, 7): "Labor Day",
    date(2026, 11, 26): "Thanksgiving Day",
    date(2026, 12, 25): "Christmas Day",
    # 2027
    date(2027, 1, 1): "New Year's Day",
    date(2027, 1, 18): "Martin Luther King Jr. Day",
    date(2027, 2, 15): "Washington's Birthday",
    date(2027, 3, 26): "Good Friday",
    date(2027, 5, 31): "Memorial Day",
    date(2027, 6, 18): "Juneteenth (observed)",
    date(2027, 7, 5): "Independence Day (observed)",
    date(2027, 9, 6): "Labor Day",
    date(2027, 11, 25): "Thanksgiving Day",
    date(2027, 12, 24): "Christmas Day (observed)",
}

#: Sessions that close at 13:00 ET.
EARLY_CLOSES: frozenset[date] = frozenset(
    {
        date(2026, 11, 27),
        date(2026, 12, 24),
        date(2027, 11, 26),
    }
)

Session = Literal["pre", "regular", "post", "closed"]


def calendar_covers(year: int) -> bool:
    return any(d.year == year for d in HOLIDAYS)


def is_trading_day(day: date) -> bool:
    return day.weekday() < 5 and day not in HOLIDAYS


def session_close_time(day: date) -> time:
    return EARLY_CLOSE if day in EARLY_CLOSES else REGULAR_CLOSE


def session_bounds(day: date) -> tuple[datetime, datetime]:
    """Regular-session open and close for `day`, as aware UTC datetimes."""
    open_local = datetime.combine(day, REGULAR_OPEN, tzinfo=EXCHANGE_TZ)
    close_local = datetime.combine(day, session_close_time(day), tzinfo=EXCHANGE_TZ)
    return open_local.astimezone(UTC), close_local.astimezone(UTC)


def previous_trading_day(day: date) -> date:
    candidate = day - timedelta(days=1)
    while not is_trading_day(candidate):
        candidate -= timedelta(days=1)
    return candidate


def next_trading_day(day: date) -> date:
    candidate = day + timedelta(days=1)
    while not is_trading_day(candidate):
        candidate += timedelta(days=1)
    return candidate


@dataclass(frozen=True)
class MarketStatus:
    is_open: bool
    session: Session
    #: Why the market is closed, in words a user can read. None when open.
    reason: str | None
    #: The most recent regular session that has *completed* - its close is what
    #: the dashboard shows while the market is shut.
    last_completed_session: date
    #: The session a live quote belongs to right now, if any.
    current_session: date | None
    next_open: datetime
    next_close: datetime | None


def market_status(now: datetime) -> MarketStatus:
    if now.tzinfo is None:
        raise ValueError("market_status requires an aware datetime")

    local = now.astimezone(EXCHANGE_TZ)
    today = local.date()

    if is_trading_day(today):
        open_utc, close_utc = session_bounds(today)
        if open_utc <= now < close_utc:
            return MarketStatus(
                is_open=True,
                session="regular",
                reason=None,
                last_completed_session=previous_trading_day(today),
                current_session=today,
                next_open=session_bounds(next_trading_day(today))[0],
                next_close=close_utc,
            )
        if now < open_utc:
            pre = local.time() >= PRE_MARKET_OPEN
            return MarketStatus(
                is_open=False,
                session="pre" if pre else "closed",
                reason="Pre-market" if pre else "Market closed overnight",
                last_completed_session=previous_trading_day(today),
                current_session=None,
                next_open=open_utc,
                next_close=close_utc,
            )
        # After today's close.
        post = local.time() < POST_MARKET_CLOSE and today not in EARLY_CLOSES
        next_day = next_trading_day(today)
        return MarketStatus(
            is_open=False,
            session="post" if post else "closed",
            reason="After hours" if post else "Market closed for the day",
            last_completed_session=today,
            current_session=None,
            next_open=session_bounds(next_day)[0],
            next_close=session_bounds(next_day)[1],
        )

    reason = HOLIDAYS.get(today) or "Weekend"
    next_day = next_trading_day(today)
    return MarketStatus(
        is_open=False,
        session="closed",
        reason=f"Market closed · {reason}",
        last_completed_session=previous_trading_day(today),
        current_session=None,
        next_open=session_bounds(next_day)[0],
        next_close=session_bounds(next_day)[1],
    )
