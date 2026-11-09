"""The AI analyst endpoint.

Two gates, in this order:

  1. `require_feature(AI_MESSAGES_PER_DAY)` - does this plan include the analyst
     at all? Returns 402, which the web app turns into an upgrade prompt.
  2. The quota - has this user spent their daily or hourly allowance? Also 402,
     with the counts, so the UI can say "5 of 5 used today" rather than "error".

Both limits are read from the plan matrix and counted from `ai_messages` in
Postgres, per request. Never from a JWT claim (rule 2) and never from Redis: a
quota that resets when a cache is flushed is not a quota.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select

from app.auth.deps import CurrentEntitlements, CurrentUser, DbSession, require_feature
from app.core.clock import Clock, get_clock
from app.core.logging import get_logger
from app.llm import LLMClient, get_llm_client
from app.llm.base import LLMError
from app.models.analyst import AiMessage
from app.models.feed import FeedItem
from app.models.plan import UNLIMITED
from app.schemas.analyst import (
    AnalystStatusOut,
    AnswerOut,
    AskIn,
    CitationOut,
    UsageOut,
)
from app.services import analyst as analyst_service
from app.services import entitlements as ent
from app.services import features as F

router = APIRouter(prefix="/ai", tags=["ai"])
log = get_logger("api.analyst")

ClockDep = Annotated[Clock, Depends(get_clock)]


def get_llm() -> LLMClient:
    """Dependency so tests can swap in a stub or a failing client."""
    return get_llm_client()


LLM = Annotated[LLMClient, Depends(get_llm)]


def _used_since(db: DbSession, user_id, since) -> int:
    return (
        db.scalar(
            select(func.count(AiMessage.id)).where(
                AiMessage.user_id == user_id, AiMessage.created_at >= since
            )
        )
        or 0
    )


def usage_for(db: DbSession, user_id, entitlements: ent.Entitlements, now) -> UsageOut:
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    hour_start = now.replace(minute=0, second=0, microsecond=0)
    return UsageOut(
        used_today=_used_since(db, user_id, day_start),
        daily_limit=entitlements.limit(F.AI_MESSAGES_PER_DAY),
        used_this_hour=_used_since(db, user_id, hour_start),
        hourly_limit=entitlements.limit(F.AI_MESSAGES_PER_HOUR),
    )


def _enforce_quota(usage: UsageOut) -> None:
    """402 when the allowance is spent, naming which window ran out.

    The hourly limit is the fair-use guard on plans whose daily limit is
    UNLIMITED: "fair use" has to mean something enforceable, or Pro is an
    unmetered bill waiting to happen.
    """
    for used, ceiling, window in (
        (usage.used_today, usage.daily_limit, "day"),
        (usage.used_this_hour, usage.hourly_limit, "hour"),
    ):
        if ceiling != UNLIMITED and used >= ceiling:
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail={
                    "error": "quota_exceeded",
                    "window": window,
                    "used": used,
                    "limit": ceiling,
                    "feature": F.AI_MESSAGES_PER_DAY,
                },
            )


@router.get("/status", response_model=AnalystStatusOut)
def status_(
    db: DbSession,
    user: CurrentUser,
    entitlements: CurrentEntitlements,
    clock: ClockDep,
    _: Annotated[ent.Entitlements, Depends(require_feature(F.AI_MESSAGES_PER_DAY))],
) -> AnalystStatusOut:
    now = clock()
    searchable = (
        db.scalar(select(func.count(FeedItem.id)).where(FeedItem.embedding.is_not(None))) or 0
    )
    return AnalystStatusOut(
        server_time=now,
        usage=usage_for(db, user.id, entitlements, now),
        searchable_articles=searchable,
    )


@router.post("/ask", response_model=AnswerOut)
def ask(
    payload: AskIn,
    db: DbSession,
    user: CurrentUser,
    entitlements: CurrentEntitlements,
    client: LLM,
    clock: ClockDep,
    _: Annotated[ent.Entitlements, Depends(require_feature(F.AI_MESSAGES_PER_DAY))],
) -> AnswerOut:
    now = clock()
    _enforce_quota(usage_for(db, user.id, entitlements, now))

    try:
        answer = analyst_service.ask(
            db, client, user.id, payload.question, now, symbol=payload.symbol
        )
    except LLMError as exc:
        # The model is the dependency most likely to be down. A 503 says "try
        # again", which is true, rather than a 500 that reads as our bug.
        log.warning("analyst_unavailable", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error": "analyst_unavailable"},
        ) from exc

    return AnswerOut(
        answer=answer.text,
        citations=[CitationOut(**c.to_json()) for c in answer.citations],
        retrieved=answer.retrieved,
        model=answer.model,
        server_time=now,
        # Re-read after the write, so the counts include the question just asked.
        usage=usage_for(db, user.id, entitlements, now),
    )
