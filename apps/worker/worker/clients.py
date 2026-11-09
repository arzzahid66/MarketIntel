"""Shared clients. The worker uses the API package's Redis client rather than its own,
so both processes agree on connection settings, the rate-limit keys and the
update channel."""

from __future__ import annotations

from app.core.redis import get_redis

__all__ = ["get_redis"]
