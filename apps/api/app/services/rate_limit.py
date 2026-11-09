"""Token-bucket rate limiting for outbound provider calls.

The API (on-demand revalidation) and the worker (scheduled ingest) both call the
same provider with the same key, so the bucket has to be shared between
processes. It lives in Redis and is updated atomically by a Lua script using the
Redis server's clock, so processes with drifting clocks still agree.

Without Redis (unit tests, a Redis outage) each process falls back to its own
in-memory bucket. That can briefly exceed the provider limit across processes,
which is why the configured rates sit below the published ones.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass

import redis

from app.core.logging import get_logger
from app.core.redis import report_redis_failure

log = get_logger("services.rate_limit")

_TOKEN_BUCKET_LUA = """
local key = KEYS[1]
local capacity = tonumber(ARGV[1])
local rate = tonumber(ARGV[2])
local requested = tonumber(ARGV[3])
local t = redis.call('TIME')
local now = tonumber(t[1]) + tonumber(t[2]) / 1000000

local state = redis.call('HMGET', key, 'tokens', 'ts')
local tokens = tonumber(state[1])
local ts = tonumber(state[2])
if tokens == nil then
  tokens = capacity
  ts = now
end

tokens = math.min(capacity, tokens + math.max(0, now - ts) * rate)
local allowed = 0
local wait = 0
if tokens >= requested then
  tokens = tokens - requested
  allowed = 1
else
  wait = (requested - tokens) / rate
end

redis.call('HSET', key, 'tokens', tokens, 'ts', now)
redis.call('PEXPIRE', key, math.ceil(capacity / rate * 1000) + 1000)
return {allowed, tostring(wait)}
"""


class RateLimitExceeded(Exception):
    def __init__(self, key: str, retry_after: float) -> None:
        super().__init__(f"Rate limit for {key!r} exceeded; retry in {retry_after:.2f}s")
        self.key = key
        self.retry_after = retry_after


@dataclass(frozen=True)
class Decision:
    allowed: bool
    retry_after: float


class TokenBucket:
    """`capacity` tokens, refilled continuously at `per_minute` tokens a minute."""

    def __init__(
        self,
        key: str,
        per_minute: float,
        capacity: float | None = None,
        client: redis.Redis | None = None,
    ) -> None:
        if per_minute <= 0:
            raise ValueError("per_minute must be positive")
        self.key = f"ratelimit:{key}"
        self.rate = per_minute / 60.0
        # Burst defaults to a tenth of the minute budget, at least one call, so a
        # full bucket cannot fire a minute's worth of calls in one second.
        self.capacity = capacity if capacity is not None else max(1.0, per_minute / 10.0)
        self._client = client
        self._script = client.register_script(_TOKEN_BUCKET_LUA) if client is not None else None
        self._lock = threading.Lock()
        self._tokens = self.capacity
        self._updated = time.monotonic()

    def try_acquire(self, tokens: float = 1.0) -> Decision:
        if self._script is not None:
            try:
                allowed, wait = self._script(
                    keys=[self.key], args=[self.capacity, self.rate, tokens]
                )
                return Decision(bool(int(allowed)), float(wait))
            except redis.RedisError as exc:
                report_redis_failure(exc)
                log.warning("rate_limit_redis_fallback", key=self.key, error=str(exc))
        return self._local_try_acquire(tokens)

    def acquire(self, tokens: float = 1.0, timeout: float = 30.0) -> None:
        """Block until a token is available, or raise after `timeout` seconds."""
        deadline = time.monotonic() + timeout
        while True:
            decision = self.try_acquire(tokens)
            if decision.allowed:
                return
            remaining = deadline - time.monotonic()
            if decision.retry_after > remaining:
                raise RateLimitExceeded(self.key, decision.retry_after)
            time.sleep(max(decision.retry_after, 0.01))

    def _local_try_acquire(self, tokens: float) -> Decision:
        with self._lock:
            now = time.monotonic()
            self._tokens = min(self.capacity, self._tokens + (now - self._updated) * self.rate)
            self._updated = now
            if self._tokens >= tokens:
                self._tokens -= tokens
                return Decision(True, 0.0)
            return Decision(False, (tokens - self._tokens) / self.rate)
