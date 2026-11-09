"""The token bucket runs against real Redis: it is a Lua script, and the property
that matters - two processes sharing one limit - only exists in Redis."""

from __future__ import annotations

import time
import uuid

import pytest

from app.core.redis import get_redis
from app.services.rate_limit import RateLimitExceeded, TokenBucket


def key() -> str:
    return f"test-{uuid.uuid4().hex[:8]}"


@pytest.fixture
def redis_client():  # type: ignore[no-untyped-def]
    client = get_redis()
    if client is None:
        pytest.skip("Redis is not available")
    return client


def test_burst_up_to_capacity_then_denied(redis_client) -> None:  # type: ignore[no-untyped-def]
    bucket = TokenBucket(key(), per_minute=60, capacity=3, client=redis_client)
    assert [bucket.try_acquire().allowed for _ in range(3)] == [True, True, True]
    denied = bucket.try_acquire()
    assert not denied.allowed
    assert 0 < denied.retry_after <= 1.05


def test_two_processes_share_one_limit(redis_client) -> None:  # type: ignore[no-untyped-def]
    """The API and the worker each build their own bucket object for the same key."""
    shared = key()
    api = TokenBucket(shared, per_minute=60, capacity=2, client=redis_client)
    worker = TokenBucket(shared, per_minute=60, capacity=2, client=redis_client)
    assert api.try_acquire().allowed
    assert worker.try_acquire().allowed
    assert not api.try_acquire().allowed
    assert not worker.try_acquire().allowed


def test_tokens_refill_over_time(redis_client) -> None:  # type: ignore[no-untyped-def]
    bucket = TokenBucket(key(), per_minute=600, capacity=1, client=redis_client)  # 10/s
    assert bucket.try_acquire().allowed
    assert not bucket.try_acquire().allowed
    time.sleep(0.15)
    assert bucket.try_acquire().allowed


def test_acquire_waits_for_a_token(redis_client) -> None:  # type: ignore[no-untyped-def]
    bucket = TokenBucket(key(), per_minute=600, capacity=1, client=redis_client)
    bucket.acquire()
    started = time.monotonic()
    bucket.acquire(timeout=2)
    assert 0.05 < time.monotonic() - started < 1.0


def test_acquire_gives_up_rather_than_blocking_past_its_timeout(redis_client) -> None:  # type: ignore[no-untyped-def]
    bucket = TokenBucket(key(), per_minute=1, capacity=1, client=redis_client)
    bucket.acquire()
    with pytest.raises(RateLimitExceeded) as exc:
        bucket.acquire(timeout=0.1)
    assert exc.value.retry_after > 1


def test_in_memory_fallback_enforces_the_same_rules() -> None:
    bucket = TokenBucket(key(), per_minute=60, capacity=2, client=None)
    assert bucket.try_acquire().allowed
    assert bucket.try_acquire().allowed
    assert not bucket.try_acquire().allowed


def test_rate_must_be_positive() -> None:
    with pytest.raises(ValueError):
        TokenBucket(key(), per_minute=0)
