from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from app.services.market_hours import (
    calendar_covers,
    is_trading_day,
    market_status,
    next_trading_day,
    previous_trading_day,
    session_bounds,
)


def at(*args: int) -> datetime:
    return datetime(*args, tzinfo=UTC)


def test_regular_session_is_open() -> None:
    status = market_status(at(2026, 9, 14, 16, 0))  # Monday 12:00 ET
    assert status.is_open
    assert status.session == "regular"
    assert status.current_session == date(2026, 9, 14)
    assert status.last_completed_session == date(2026, 9, 11)
    assert status.next_close == at(2026, 9, 14, 20, 0)


@pytest.mark.parametrize(
    ("instant", "is_open"),
    [
        (at(2026, 9, 14, 13, 29, 59), False),  # 09:29:59 ET
        (at(2026, 9, 14, 13, 30, 0), True),  # 09:30:00 ET - the open is inclusive
        (at(2026, 9, 14, 19, 59, 59), True),
        (at(2026, 9, 14, 20, 0, 0), False),  # 16:00:00 ET - the close is exclusive
    ],
)
def test_open_and_close_boundaries(instant: datetime, is_open: bool) -> None:
    assert market_status(instant).is_open is is_open


def test_pre_market_and_after_hours_are_labelled_and_closed() -> None:
    pre = market_status(at(2026, 9, 14, 12, 0))  # 08:00 ET
    assert (pre.is_open, pre.session) == (False, "pre")
    assert pre.last_completed_session == date(2026, 9, 11)

    post = market_status(at(2026, 9, 14, 21, 0))  # 17:00 ET
    assert (post.is_open, post.session) == (False, "post")
    # After today's close, today *is* the last completed session.
    assert post.last_completed_session == date(2026, 9, 14)


def test_weekend_points_at_fridays_close_and_mondays_open() -> None:
    status = market_status(at(2026, 9, 12, 16, 0))  # Saturday
    assert not status.is_open
    assert "Weekend" in (status.reason or "")
    assert status.last_completed_session == date(2026, 9, 11)
    assert status.next_open == at(2026, 9, 14, 13, 30)


def test_holiday_is_closed_and_named() -> None:
    status = market_status(at(2026, 7, 3, 15, 0))  # Independence Day (observed)
    assert not status.is_open
    assert "Independence Day" in (status.reason or "")
    assert status.last_completed_session == date(2026, 7, 2)
    assert status.next_open == at(2026, 7, 6, 13, 30)


def test_early_close_day_shuts_at_1pm() -> None:
    open_utc, close_utc = session_bounds(date(2026, 11, 27))
    assert close_utc == at(2026, 11, 27, 18, 0)  # 13:00 EST
    assert market_status(at(2026, 11, 27, 17, 59)).is_open
    assert not market_status(at(2026, 11, 27, 18, 30)).is_open


def test_daylight_saving_shifts_the_utc_open() -> None:
    """DST started on 8 March 2026. The open stays 09:30 in New York, so it moves in UTC."""
    assert session_bounds(date(2026, 3, 6))[0] == at(2026, 3, 6, 14, 30)  # EST
    assert session_bounds(date(2026, 3, 9))[0] == at(2026, 3, 9, 13, 30)  # EDT


def test_trading_day_navigation_skips_weekends_and_holidays() -> None:
    assert not is_trading_day(date(2026, 11, 26))  # Thanksgiving
    assert next_trading_day(date(2026, 11, 25)) == date(2026, 11, 27)
    assert previous_trading_day(date(2026, 9, 8)) == date(2026, 9, 4)  # over Labor Day


def test_naive_datetimes_are_rejected() -> None:
    with pytest.raises(ValueError):
        market_status(datetime(2026, 9, 14, 12, 0))


def test_holiday_calendar_covers_the_launch_years() -> None:
    assert calendar_covers(2026)
    assert calendar_covers(2027)
