"""Community chatrooms.

Two different gates, which is the point of having two feature keys:

  * `CHAT_CAN_READ` - Free included. Reading the room is part of the free
    product.
  * `CHAT_CAN_POST` - Plus and above. Posting returns 402 on Free, which the web
    app turns into an upgrade prompt beside the composer.

Moderation is `is_admin` on the user row, not a plan feature: moderating is a
staff job, not something a subscription buys.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.auth.deps import CurrentEntitlements, CurrentUser, DbSession
from app.core.clock import Clock, get_clock
from app.llm import LLMClient, get_llm_client
from app.models.chat import ChatMessage
from app.schemas.chat import (
    ChatHistoryOut,
    ChatMessageOut,
    ChatRoomOut,
    FlagIn,
    FlagOut,
    ModerateIn,
    PostMessageIn,
    PostMessageOut,
)
from app.services import chat as chat_service
from app.services import entitlements as ent
from app.services import features as F
from app.services.chat import ChatError

router = APIRouter(prefix="/chat", tags=["chat"])

ClockDep = Annotated[Clock, Depends(get_clock)]


def get_llm() -> LLMClient:
    """Dependency so tests can swap the spam classifier."""
    return get_llm_client()


LLM = Annotated[LLMClient, Depends(get_llm)]


def _require_read(entitlements: ent.Entitlements) -> None:
    if not entitlements.allows(F.CHAT_CAN_READ):
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail={"error": "upgrade_required", "feature": F.CHAT_CAN_READ},
        )


def _message_out(message: ChatMessage, *, moderator: bool) -> ChatMessageOut:
    return ChatMessageOut(
        id=str(message.id),
        body=message.body,
        author=message.author.email.split("@")[0],
        author_id=str(message.user_id),
        created_at=message.created_at,
        is_hidden=message.is_hidden,
        hidden_reason=message.hidden_reason,
        flags=len(message.flags),
        # Withheld from ordinary readers: publishing the screen's score tells
        # whoever is probing it exactly how close they got.
        spam_score=message.spam_score if moderator else None,
        spam_label=message.spam_label if moderator else None,
    )


@router.get("/rooms", response_model=list[ChatRoomOut])
def list_rooms(db: DbSession, entitlements: CurrentEntitlements) -> list[ChatRoomOut]:
    _require_read(entitlements)
    return [
        ChatRoomOut(slug=r.slug, name=r.name, description=r.description)
        for r in chat_service.rooms(db)
    ]


def _room_or_404(db: DbSession, slug: str):
    room = chat_service.room_by_slug(db, slug)
    if room is None:
        raise HTTPException(status_code=404, detail={"error": "room_not_found"})
    return room


@router.get("/rooms/{slug}", response_model=ChatHistoryOut)
def history(
    slug: str,
    db: DbSession,
    user: CurrentUser,
    entitlements: CurrentEntitlements,
    clock: ClockDep,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> ChatHistoryOut:
    _require_read(entitlements)
    room = _room_or_404(db, slug)
    moderator = bool(user.is_admin)
    messages = chat_service.recent_messages(db, room, limit=limit, include_hidden=moderator)

    return ChatHistoryOut(
        server_time=clock(),
        room=ChatRoomOut(slug=room.slug, name=room.name, description=room.description),
        messages=[_message_out(m, moderator=moderator) for m in messages],
        can_post=entitlements.allows(F.CHAT_CAN_POST),
    )


@router.post("/rooms/{slug}", response_model=PostMessageOut, status_code=201)
def post(
    slug: str,
    payload: PostMessageIn,
    db: DbSession,
    user: CurrentUser,
    entitlements: CurrentEntitlements,
    client: LLM,
    clock: ClockDep,
) -> PostMessageOut:
    # Posting is the gated half; reading is free.
    if not entitlements.allows(F.CHAT_CAN_POST):
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail={
                "error": "upgrade_required",
                "feature": F.CHAT_CAN_POST,
                "current_plan": entitlements.plan_code,
            },
        )

    room = _room_or_404(db, slug)
    try:
        result = chat_service.post_message(db, client, room, user.id, payload.body, clock())
    except ChatError as exc:
        raise HTTPException(
            status_code=(
                status.HTTP_429_TOO_MANY_REQUESTS
                if exc.code == "rate_limited"
                else status.HTTP_400_BAD_REQUEST
            ),
            detail={"error": exc.code, "message": exc.message},
            headers=({"Retry-After": str(exc.retry_after)} if exc.retry_after else None),
        ) from exc

    return PostMessageOut(
        message=_message_out(result.message, moderator=bool(user.is_admin)),
        auto_hidden=result.auto_hidden,
    )


@router.post("/messages/{message_id}/flag", response_model=FlagOut)
def flag(
    message_id: uuid.UUID,
    payload: FlagIn,
    db: DbSession,
    user: CurrentUser,
    entitlements: CurrentEntitlements,
) -> FlagOut:
    """Anyone who can read the room can report a message."""
    _require_read(entitlements)
    if db.get(ChatMessage, message_id) is None:
        raise HTTPException(status_code=404, detail={"error": "message_not_found"})
    return FlagOut(flags=chat_service.flag_message(db, message_id, user.id, payload.reason))


# ---------------------------------------------------------------------------
# Moderation. Staff only - `is_admin`, not a plan feature.
# ---------------------------------------------------------------------------


def _require_moderator(user: CurrentUser) -> None:
    if not user.is_admin:
        # 403, not 402: no subscription buys this. Upgrading would not help.
        raise HTTPException(status_code=403, detail={"error": "moderator_only"})


@router.get("/moderation/queue", response_model=list[ChatMessageOut])
def queue(db: DbSession, user: CurrentUser) -> list[ChatMessageOut]:
    _require_moderator(user)
    return [_message_out(m, moderator=True) for m in chat_service.moderation_queue(db)]


@router.post("/moderation/{message_id}", response_model=ChatMessageOut)
def moderate(
    message_id: uuid.UUID,
    payload: ModerateIn,
    db: DbSession,
    user: CurrentUser,
    clock: ClockDep,
) -> ChatMessageOut:
    _require_moderator(user)
    message = db.get(ChatMessage, message_id)
    if message is None:
        raise HTTPException(status_code=404, detail={"error": "message_not_found"})
    updated = chat_service.set_hidden(db, message, payload.hidden, user.id, payload.reason, clock())
    return _message_out(updated, moderator=True)
