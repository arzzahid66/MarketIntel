"""Chatroom reads, posting, and moderation.

The posting path has three gates, and they are in this order on purpose:

  1. **Rate limit** - counted from `chat_messages` in Postgres, because a limit
     that resets when a cache is flushed is not a limit. It runs first so a
     flooder costs us a COUNT, not an LLM call.
  2. **Spam screen** - deterministic first, model only when unsure
     (`chat_spam.py`).
  3. **Store, and hide on arrival** if the score clears `AUTO_HIDE_AT`. The
     message is still written: the author sees their own post, a moderator sees
     it in the queue, and nothing silently vanishes.

Reads never show hidden messages to ordinary readers, and never call a provider
or a model.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.llm.base import LLMClient
from app.models.chat import AUTO_HIDE_AT, ChatFlag, ChatMessage, ChatRoom
from app.services import chat_spam

log = get_logger("services.chat")

#: Posts allowed per user per window, across all rooms. Generous for a person
#: in a conversation, useless for a script. Enforced regardless of plan: a Pro
#: subscription buys access, not the right to flood the room.
RATE_LIMIT_POSTS = 10
RATE_LIMIT_WINDOW = timedelta(minutes=5)

#: Identical text from the same person inside this window is a repeat post.
#: Catches the copy-paste flood that stays under the rate limit.
DUPLICATE_WINDOW = timedelta(minutes=30)

MAX_BODY_LENGTH = 2000


class ChatError(Exception):
    """A post refused for a reason the author should see."""

    def __init__(self, code: str, message: str, retry_after: int | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retry_after = retry_after


@dataclass(frozen=True)
class PostResult:
    message: ChatMessage
    #: True when the spam screen hid it on arrival. The author is told plainly
    #: rather than being shadow-banned - a post that silently vanishes teaches
    #: people the product is broken.
    auto_hidden: bool


def rooms(db: Session) -> list[ChatRoom]:
    return list(
        db.scalars(
            select(ChatRoom).where(ChatRoom.is_active.is_(True)).order_by(ChatRoom.sort_order)
        )
    )


def room_by_slug(db: Session, slug: str) -> ChatRoom | None:
    return db.scalars(
        select(ChatRoom).where(ChatRoom.slug == slug, ChatRoom.is_active.is_(True))
    ).first()


def recent_messages(
    db: Session,
    room: ChatRoom,
    limit: int = 50,
    include_hidden: bool = False,
) -> list[ChatMessage]:
    """Newest-last, the order a conversation reads in.

    `include_hidden` is for moderators only; the route decides who qualifies,
    never this function.
    """
    statement = (
        select(ChatMessage)
        .where(ChatMessage.room_id == room.id)
        .order_by(ChatMessage.created_at.desc())
        .limit(limit)
    )
    if not include_hidden:
        statement = statement.where(ChatMessage.is_hidden.is_(False))
    return list(reversed(list(db.scalars(statement).unique())))


def _check_rate_limit(db: Session, user_id: uuid.UUID, now: datetime) -> None:
    since = now - RATE_LIMIT_WINDOW
    recent = (
        db.scalar(
            select(func.count(ChatMessage.id)).where(
                ChatMessage.user_id == user_id, ChatMessage.created_at >= since
            )
        )
        or 0
    )
    if recent >= RATE_LIMIT_POSTS:
        raise ChatError(
            "rate_limited",
            f"You can post {RATE_LIMIT_POSTS} messages every "
            f"{int(RATE_LIMIT_WINDOW.total_seconds() // 60)} minutes.",
            retry_after=int(RATE_LIMIT_WINDOW.total_seconds()),
        )


def _check_duplicate(db: Session, user_id: uuid.UUID, body: str, now: datetime) -> None:
    since = now - DUPLICATE_WINDOW
    repeated = db.scalars(
        select(ChatMessage.id)
        .where(
            ChatMessage.user_id == user_id,
            ChatMessage.created_at >= since,
            ChatMessage.body == body,
        )
        .limit(1)
    ).first()
    if repeated is not None:
        raise ChatError("duplicate", "You have already posted that message.")


def post_message(
    db: Session,
    client: LLMClient,
    room: ChatRoom,
    user_id: uuid.UUID,
    body: str,
    now: datetime,
) -> PostResult:
    """Rate limit, screen, store. Raises ChatError for anything the author caused."""
    text = body.strip()
    if not text:
        raise ChatError("empty", "A message cannot be empty.")
    if len(text) > MAX_BODY_LENGTH:
        raise ChatError("too_long", f"Messages are limited to {MAX_BODY_LENGTH} characters.")

    _check_rate_limit(db, user_id, now)
    _check_duplicate(db, user_id, text, now)

    assessment = chat_spam.classify(client, text)
    auto_hidden = assessment.score >= AUTO_HIDE_AT

    message = ChatMessage(
        room_id=room.id,
        user_id=user_id,
        body=text,
        spam_score=assessment.score,
        spam_label=assessment.label,
        spam_reason=assessment.reason,
        spam_source=assessment.source,
        is_hidden=auto_hidden,
        hidden_reason=f"Automatic spam screen: {assessment.reason}" if auto_hidden else None,
        hidden_at=now if auto_hidden else None,
        # Left null on purpose: no human hid this, and the moderation queue
        # distinguishes "the screen did it" from "a person decided".
        hidden_by_user_id=None,
        created_at=now,
    )
    db.add(message)
    db.commit()
    db.refresh(message)

    if auto_hidden:
        log.info(
            "chat_message_auto_hidden",
            score=assessment.score,
            reason=assessment.reason,
            source=assessment.source,
        )
    return PostResult(message=message, auto_hidden=auto_hidden)


def flag_message(db: Session, message_id: uuid.UUID, user_id: uuid.UUID, reason: str | None) -> int:
    """Report a message. Idempotent per reader; returns the total flag count."""
    existing = db.scalars(
        select(ChatFlag).where(ChatFlag.message_id == message_id, ChatFlag.user_id == user_id)
    ).first()
    if existing is None:
        db.add(
            ChatFlag(
                message_id=message_id,
                user_id=user_id,
                reason=(reason or "").strip()[:200] or None,
            )
        )
        db.commit()
    return db.scalar(select(func.count(ChatFlag.id)).where(ChatFlag.message_id == message_id)) or 0


def set_hidden(
    db: Session,
    message: ChatMessage,
    hidden: bool,
    moderator_id: uuid.UUID,
    reason: str | None,
    now: datetime,
) -> ChatMessage:
    """A moderator hiding or restoring a message. Always leaves a record."""
    message.is_hidden = hidden
    message.hidden_reason = (reason or "").strip()[:500] or None if hidden else None
    message.hidden_at = now if hidden else None
    message.hidden_by_user_id = moderator_id if hidden else None
    db.commit()
    db.refresh(message)
    return message


def moderation_queue(db: Session, limit: int = 50) -> list[ChatMessage]:
    """What a moderator should look at: flagged, or hidden by the screen.

    Ordered by flag count then recency, so the thing several people objected to
    is at the top rather than whatever happened last.
    """
    flag_count = (
        select(ChatFlag.message_id, func.count(ChatFlag.id).label("flags"))
        .group_by(ChatFlag.message_id)
        .subquery()
    )
    statement = (
        select(ChatMessage)
        .outerjoin(flag_count, flag_count.c.message_id == ChatMessage.id)
        .where(
            (flag_count.c.flags > 0)
            | (ChatMessage.is_hidden.is_(True))
            | (ChatMessage.spam_label == "spam")
        )
        .order_by(func.coalesce(flag_count.c.flags, 0).desc(), ChatMessage.created_at.desc())
        .limit(limit)
    )
    return list(db.scalars(statement).unique())
