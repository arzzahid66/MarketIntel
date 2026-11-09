"""Redis being down must make data staler, never pages slower.

Without the breaker, every request re-attempted a connection and waited out the
connect timeout - measured at ~4 s per dashboard request with Redis stopped.
"""

from __future__ import annotations

import time
from collections.abc import Iterator

import pytest

from app.core import redis as redis_module
from app.core.redis import get_redis, report_redis_failure, reset_clients

DEAD_REDIS = "redis://127.0.0.1:6399/0"  # nothing listens here


@pytest.fixture(autouse=True)
def isolated_breaker(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    reset_clients()
    yield
    monkeypatch.undo()
    reset_clients()


def test_after_one_failure_a_dead_redis_costs_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(redis_module.settings, "redis_url", DEAD_REDIS)
    reset_clients()

    assert get_redis() is None  # pays the connect timeout once

    started = time.perf_counter()
    for _ in range(20):
        assert get_redis() is None
    assert time.perf_counter() - started < 0.05, "breaker must answer without touching the network"


def test_breaker_retries_after_the_down_window(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(redis_module, "DOWN_SECONDS", 0.2)
    assert get_redis() is not None

    report_redis_failure(RuntimeError("simulated mid-request failure"))
    assert get_redis() is None

    time.sleep(0.25)
    assert get_redis() is not None, "a recovered Redis must be picked up again"


def test_healthy_redis_is_not_pinged_on_every_call(monkeypatch: pytest.MonkeyPatch) -> None:
    client = get_redis()
    assert client is not None
    pings = 0
    original = client.ping

    def counting_ping(*args, **kwargs):  # type: ignore[no-untyped-def]
        nonlocal pings
        pings += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(client, "ping", counting_ping)
    for _ in range(50):
        assert get_redis() is client
    assert pings == 0
