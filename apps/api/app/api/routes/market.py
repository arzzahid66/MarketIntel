"""Market dashboard endpoints: snapshot, debounced refresh, and live SSE stream.

None of these wait on a market data provider. Outbound calls happen in a
background task, behind a Redis lock and the shared token bucket, so a slow or
failing provider can make data stale but can never make a page slow or broken.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import time
import uuid
from collections.abc import AsyncIterator
from datetime import timedelta
from typing import Annotated, Any, Protocol

import redis
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from starlette.concurrency import run_in_threadpool

from app.auth.deps import CurrentEntitlements, DbSession, OptionalUser
from app.core.clock import Clock, get_clock
from app.core.logging import get_logger
from app.core.redis import get_async_redis, get_redis, report_redis_failure
from app.db.session import SessionLocal
from app.models.user import User
from app.providers import MarketDataProvider, get_market_data_provider
from app.schemas.market import DashboardOut, MarketStatusOut
from app.services import features as F
from app.services import market_data as md
from app.services.dashboard import build_dashboard
from app.services.entitlements import resolve_anonymous, resolve_for_user
from app.services.market_hours import market_status

router = APIRouter(prefix="/market", tags=["market"])
log = get_logger("api.market")

REVALIDATE_LOCK = "lock:market:revalidate"
REVALIDATE_LOCK_SECONDS = 30
#: One browser (user or IP) may press refresh at most this often.
REFRESH_CLIENT_COOLDOWN_SECONDS = 5
#: A quote fetched this recently is fresh enough; refresh will not refetch it.
REFRESH_FRESH_ENOUGH = timedelta(seconds=15)
SSE_HEARTBEAT_SECONDS = 15.0


def get_provider() -> MarketDataProvider:
    """Dependency so tests can swap in a spy or a failing provider."""
    return get_market_data_provider()


Provider = Annotated[MarketDataProvider, Depends(get_provider)]
ClockDep = Annotated[Clock, Depends(get_clock)]


def revalidate_quotes(provider: MarketDataProvider, clock: Clock) -> bool:
    """Fetch fresh quotes unless another process already is. Returns whether it ran.

    Runs after the response is sent. Every failure is swallowed and logged: the
    user already has last-known values, and the next cycle will try again.
    """
    client = get_redis()
    if client is not None:
        try:
            if not client.set(REVALIDATE_LOCK, "1", nx=True, ex=REVALIDATE_LOCK_SECONDS):
                return False
        except redis.RedisError as exc:
            report_redis_failure(exc)
            return False
    try:
        with SessionLocal() as db:
            result = md.ingest_quotes(db, provider, md.big7_tickers(db), clock(), client)
        log.info("quotes_revalidated", updated=len(result.updated), failed=len(result.failed))
        return True
    except Exception:
        log.exception("quote_revalidation_failed")
        return False


def _schedule_revalidation(
    background: BackgroundTasks, provider: MarketDataProvider, clock: Clock
) -> bool:
    client = get_redis()
    if client is not None:
        try:
            if client.exists(REVALIDATE_LOCK):
                return False
        except redis.RedisError as exc:
            report_redis_failure(exc)
    background.add_task(revalidate_quotes, provider, clock)
    return True


def client_ip(request: Request) -> str:
    """The browser's IP for per-client throttling.

    Every request reaches FastAPI through the Next.js server, so the socket peer
    is always that server; without X-Forwarded-For one anonymous visitor's
    cooldown would lock out every other anonymous visitor. The header can be
    spoofed, which only lets a client dodge its own 5-second cooldown - the
    shared fetch lock and freshness check still protect the provider.
    """
    forwarded = request.headers.get("x-forwarded-for", "")
    first = forwarded.split(",")[0].strip()
    if first:
        return first
    return request.client.host if request.client else "unknown"


@router.get("/status", response_model=MarketStatusOut)
def get_market_status(clock: ClockDep) -> MarketStatusOut:
    s = market_status(clock())
    return MarketStatusOut(
        is_open=s.is_open,
        session=s.session,
        reason=s.reason,
        last_completed_session=s.last_completed_session,
        next_open=s.next_open,
        next_close=s.next_close,
    )


@router.get("/dashboard", response_model=DashboardOut)
def dashboard(
    db: DbSession,
    entitlements: CurrentEntitlements,
    background: BackgroundTasks,
    provider: Provider,
    clock: ClockDep,
) -> DashboardOut:
    result = build_dashboard(
        db,
        get_redis(),
        md.big7_tickers(db),
        clock(),
        entitlements.limit(F.REFRESH_INTERVAL_SECONDS),
        provider,
    )
    if result.needs_revalidation:
        result.dashboard.revalidating = _schedule_revalidation(background, provider, clock)
    return result.dashboard


@router.post("/refresh", response_model=DashboardOut)
def refresh(
    request: Request,
    db: DbSession,
    user: OptionalUser,
    entitlements: CurrentEntitlements,
    background: BackgroundTasks,
    provider: Provider,
    clock: ClockDep,
) -> DashboardOut:
    """The refresh button. Debounced on the server, so it cannot hammer a provider:

    1. Each client gets one press per REFRESH_CLIENT_COOLDOWN_SECONDS (429 after).
    2. Data fetched within REFRESH_FRESH_ENOUGH is returned as-is, no fetch.
    3. Otherwise one background fetch runs, shared by everyone pressing at once.
    """
    client = get_redis()
    if client is not None:
        who = f"user:{user.id}" if user else f"ip:{client_ip(request)}"
        try:
            accepted = client.set(
                f"throttle:market:refresh:{who}", "1", nx=True, ex=REFRESH_CLIENT_COOLDOWN_SECONDS
            )
        except redis.RedisError as exc:
            report_redis_failure(exc)
            accepted = True
        if not accepted:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={
                    "error": "refresh_throttled",
                    "retry_after": REFRESH_CLIENT_COOLDOWN_SECONDS,
                },
                headers={"Retry-After": str(REFRESH_CLIENT_COOLDOWN_SECONDS)},
            )

    now = clock()
    result = build_dashboard(
        db,
        client,
        md.big7_tickers(db),
        now,
        entitlements.limit(F.REFRESH_INTERVAL_SECONDS),
        provider,
    )
    board = result.dashboard
    fresh_enough = (
        board.last_updated_at is not None
        and now - board.last_updated_at < REFRESH_FRESH_ENOUGH
        and not result.needs_revalidation
    )
    worth_fetching = board.market.is_open or result.needs_revalidation
    if worth_fetching and not fresh_enough:
        board.revalidating = _schedule_revalidation(background, provider, clock)
    return board


# ---------------------------------------------------------------------------
# Server-sent events
# ---------------------------------------------------------------------------


class Disconnectable(Protocol):
    async def is_disconnected(self) -> bool: ...


def _snapshot(
    user_id: uuid.UUID | None, clock: Clock, provider: MarketDataProvider
) -> tuple[dict[str, Any], int]:
    """A full dashboard plus the viewer's push interval, from a fresh session.

    Entitlements are re-resolved on every push, so a downgrade slows a stream
    that is already open rather than waiting for a reconnect.
    """
    with SessionLocal() as db:
        user = db.get(User, user_id) if user_id else None
        entitlements = (
            resolve_for_user(db, user) if user and user.is_active else resolve_anonymous(db)
        )
        interval = entitlements.limit(F.REFRESH_INTERVAL_SECONDS)
        result = build_dashboard(db, get_redis(), md.big7_tickers(db), clock(), interval, provider)
        return result.dashboard.model_dump(mode="json"), interval


def _sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, separators=(',', ':'))}\n\n"


async def market_event_stream(
    request: Disconnectable,
    user_id: uuid.UUID | None,
    clock: Clock,
    provider: MarketDataProvider,
    *,
    poll_seconds: float = 1.0,
    heartbeat_seconds: float = SSE_HEARTBEAT_SECONDS,
    max_events: int | None = None,
) -> AsyncIterator[str]:
    """Push a snapshot when the worker publishes an update, at most once per the
    viewer's plan refresh interval (Free 5 min, Plus 60 s, Pro 15 s).

    Without Redis there is no update bus, so it pushes on the interval instead.
    `max_events` exists for tests; the endpoint streams until the client leaves.
    """
    aclient = get_async_redis()
    pubsub = None
    if aclient is not None:
        try:
            pubsub = aclient.pubsub()
            await pubsub.subscribe(md.UPDATES_CHANNEL)
        except Exception as exc:  # noqa: BLE001 - degrade to interval pushes
            log.warning("sse_pubsub_unavailable", error=str(exc))
            pubsub = None

    try:
        # Tell EventSource to wait 5 s before reconnecting, not its 3 s default.
        yield "retry: 5000\n\n"
        payload, interval = await run_in_threadpool(_snapshot, user_id, clock, provider)
        yield _sse("snapshot", payload)
        sent = 1
        last_emit = last_write = time.monotonic()
        pending = False

        while max_events is None or sent < max_events:
            if await request.is_disconnected():
                return
            if pubsub is not None:
                try:
                    message = await pubsub.get_message(
                        ignore_subscribe_messages=True, timeout=poll_seconds
                    )
                except Exception:  # noqa: BLE001
                    message = None
                    await asyncio.sleep(poll_seconds)
                pending = pending or message is not None
            else:
                await asyncio.sleep(poll_seconds)
                pending = True

            now = time.monotonic()
            if pending and now - last_emit >= interval:
                payload, interval = await run_in_threadpool(_snapshot, user_id, clock, provider)
                yield _sse("snapshot", payload)
                sent += 1
                last_emit = last_write = now
                pending = False
            elif now - last_write >= heartbeat_seconds:
                yield ": keepalive\n\n"
                last_write = now
    finally:
        # Best-effort cleanup: the client has usually already gone.
        if pubsub is not None:
            with contextlib.suppress(Exception):
                await pubsub.unsubscribe(md.UPDATES_CHANNEL)
                await pubsub.aclose()
        if aclient is not None:
            with contextlib.suppress(Exception):
                await aclient.aclose()


@router.get("/stream")
async def stream(request: Request, user: OptionalUser, provider: Provider, clock: ClockDep):
    return StreamingResponse(
        market_event_stream(request, user.id if user else None, clock, provider),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
