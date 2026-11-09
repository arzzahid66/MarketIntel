"""Redis clients shared by the API and the worker.

Redis is the cache that makes the free tier affordable, the pub/sub bus that
pushes quote updates to open dashboards, and the shared token bucket that keeps
every process inside a provider's rate limit. Callers must still behave when it
is unreachable: `get_redis()` returns None instead of raising.

It also must not make pages *slow* when unreachable. A connect attempt to a dead
Redis can block for the whole connect timeout, and a dashboard request asks for
the client more than once. So availability is a small circuit breaker:

  * healthy  - the client is returned without a round trip; a ping is re-sent at
               most every HEALTH_CHECK_SECONDS.
  * down     - after one failed ping (or a failure a caller reports), get_redis()
               returns None instantly for DOWN_SECONDS, then tries again.

Worst case during an outage: one connect timeout per process per DOWN_SECONDS,
not one per request.
"""

from __future__ import annotations

import threading
import time
from functools import lru_cache

import redis
import redis.asyncio as aioredis

from app.core.config import settings
from app.core.logging import get_logger

log = get_logger("core.redis")

CONNECT_TIMEOUT_SECONDS = 1.0
HEALTH_CHECK_SECONDS = 5.0
DOWN_SECONDS = 15.0

_lock = threading.Lock()
_healthy_until = 0.0
_down_until = 0.0


@lru_cache(maxsize=1)
def _client() -> redis.Redis | None:
    if not settings.redis_url:
        return None
    return redis.from_url(
        settings.redis_url,
        socket_connect_timeout=CONNECT_TIMEOUT_SECONDS,
        socket_timeout=2,
        decode_responses=True,
    )


def report_redis_failure(error: Exception | None = None) -> None:
    """Callers that hit a RedisError mid-operation trip the breaker too."""
    global _down_until, _healthy_until
    with _lock:
        already_down = time.monotonic() < _down_until
        _down_until = time.monotonic() + DOWN_SECONDS
        _healthy_until = 0.0
    if not already_down:
        log.warning("redis_unavailable", error=str(error) if error else None, retry_in=DOWN_SECONDS)


def get_redis() -> redis.Redis | None:
    """A usable client, or None when Redis is unset or currently down."""
    global _healthy_until
    client = _client()
    if client is None:
        return None

    now = time.monotonic()
    if now < _down_until:
        return None
    if now < _healthy_until:
        return client

    try:
        client.ping()
    except redis.RedisError as exc:
        report_redis_failure(exc)
        return None
    with _lock:
        _healthy_until = time.monotonic() + HEALTH_CHECK_SECONDS
    return client


def get_async_redis() -> aioredis.Redis | None:
    """A fresh asyncio client per long-lived stream. The caller closes it."""
    if not settings.redis_url or time.monotonic() < _down_until:
        return None
    return aioredis.from_url(
        settings.redis_url,
        decode_responses=True,
        socket_connect_timeout=CONNECT_TIMEOUT_SECONDS,
    )


def reset_clients() -> None:
    """Tests only: forget the cached client and the breaker state."""
    global _healthy_until, _down_until
    _client.cache_clear()
    with _lock:
        _healthy_until = 0.0
        _down_until = 0.0
