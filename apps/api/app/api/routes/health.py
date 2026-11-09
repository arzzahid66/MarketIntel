"""Liveness, readiness, and the deliberate-error endpoint the Sentry drill uses."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import func, select, text

from app.auth.deps import DbSession
from app.core.config import settings
from app.models.plan import Plan
from app.schemas.common import HealthResponse, ReadinessResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Liveness. Touches nothing, so a DB blip does not restart the container."""
    return HealthResponse(
        status="ok",
        environment=settings.environment,
        version=settings.api_version,
        server_time=datetime.now(UTC),
    )


@router.get("/health/ready", response_model=ReadinessResponse)
def readiness(db: DbSession) -> ReadinessResponse:
    """Readiness. Checks the dependencies a request actually needs."""
    database = "ok"
    plans_seeded = False
    try:
        db.execute(text("SELECT 1"))
        plans_seeded = (db.scalar(select(func.count()).select_from(Plan)) or 0) > 0
    except Exception:  # noqa: BLE001 - report degraded rather than 500 the probe
        database = "error"

    redis_state = "not_configured"
    if settings.redis_url:
        try:
            import redis

            client = redis.from_url(settings.redis_url, socket_connect_timeout=2)
            client.ping()
            redis_state = "ok"
        except Exception:  # noqa: BLE001
            redis_state = "error"

    overall = "ok" if database == "ok" and plans_seeded else "degraded"
    return ReadinessResponse(
        status=overall, database=database, redis=redis_state, plans_seeded=plans_seeded
    )


@router.post("/health/boom", include_in_schema=False)
def boom() -> None:
    """Phase 1 exit criterion: an intentional error shows up in Sentry.

    Admin-free on purpose but disabled in production so it cannot be used as a
    noise generator against the error budget.
    """
    if settings.is_production:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    raise RuntimeError("Intentional error to verify Sentry + structured logging wiring")
