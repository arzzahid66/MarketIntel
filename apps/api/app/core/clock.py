"""The one place the server reads the time.

Market logic ("is the market open?", "is this quote stale?") is untestable if
it calls datetime.now() directly. Routes take `Clock` as a dependency and tests
override it with a fixed instant.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

Clock = Callable[[], datetime]


def system_clock() -> datetime:
    return datetime.now(UTC)


def get_clock() -> Clock:
    """FastAPI dependency. Override with `app.dependency_overrides[get_clock]`."""
    return system_clock


def fixed_clock(instant: datetime) -> Clock:
    if instant.tzinfo is None:
        raise ValueError("fixed_clock requires an aware datetime")
    return lambda: instant
