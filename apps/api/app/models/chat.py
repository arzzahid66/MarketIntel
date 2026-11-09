"""Community chatrooms (Phase 4).

The build plan's risk register is blunt about this surface: a public finance
chatroom attracts pump-and-dump spam. The schema is shaped around that, not
around the happy path:

  * **Rooms are rows**, like plans and feed categories, so opening or closing a
    room is a database change rather than a deploy.
  * **Messages are hidden, never deleted.** A moderator hiding a post must leave
    a record of who hid it and why - deleting the evidence of abuse is exactly
    what makes abuse hard to prove later. `is_hidden` is what the read path
    filters on.
  * **Every message carries its spam assessment**, written once at post time.
    Storing the score (not just the verdict) means a threshold can be retuned
    later against real history instead of guessed at again.
  * **Flags are rows too**, one per reporter, so "three different people
    reported this" is a query rather than a counter somebody has to trust.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, uuid_pk

if TYPE_CHECKING:
    from app.models.user import User

#: Spam likelihood in [0, 1].
SpamScore = Numeric(4, 3, asdecimal=False)

#: Messages at or above this are hidden on arrival and queued for a moderator.
#: Deliberately high: a false hide silences a real person, and the rate limit
#: already blunts volume. Retune against `spam_score` history, not by feel.
AUTO_HIDE_AT = 0.85


class ChatRoom(Base, TimestampMixin):
    """One room. Data, so the room list changes without a deploy."""

    __tablename__ = "chat_rooms"

    id: Mapped[uuid.UUID] = uuid_pk()
    slug: Mapped[str] = mapped_column(String(48), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_active: Mapped[bool] = mapped_column(nullable=False, default=True)


class ChatMessage(Base):
    """One post. Hidden rather than deleted, and scored for spam on arrival."""

    __tablename__ = "chat_messages"
    __table_args__ = (
        # The read path: newest messages in one room.
        Index("ix_chat_message_room_created", "room_id", "created_at"),
        # The rate limiter: this user's recent posts, any room.
        Index("ix_chat_message_user_created", "user_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    room_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("chat_rooms.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    body: Mapped[str] = mapped_column(Text, nullable=False)

    # --- Spam assessment, written once at post time ---
    spam_score: Mapped[float | None] = mapped_column(SpamScore)
    spam_label: Mapped[str | None] = mapped_column(String(24))
    spam_reason: Mapped[str | None] = mapped_column(Text)
    #: Which screen produced the score: "heuristic" or a model name. Stored so a
    #: retune can tell cheap screening apart from model judgement.
    spam_source: Mapped[str | None] = mapped_column(String(64))

    # --- Moderation. Hidden, never deleted. ---
    is_hidden: Mapped[bool] = mapped_column(nullable=False, default=False)
    hidden_reason: Mapped[str | None] = mapped_column(Text)
    hidden_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    #: Null when the automatic screen hid it; set when a human did.
    hidden_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    author: Mapped[User] = relationship(foreign_keys=[user_id], lazy="joined")
    room: Mapped[ChatRoom] = relationship(lazy="joined")
    flags: Mapped[list[ChatFlag]] = relationship(
        back_populates="message", cascade="all, delete-orphan", lazy="selectin"
    )


class ChatFlag(Base):
    """One reader reporting one message. At most once per reader."""

    __tablename__ = "chat_flags"
    __table_args__ = (UniqueConstraint("message_id", "user_id", name="uq_chat_flag_once_per_user"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    message_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("chat_messages.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    reason: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    message: Mapped[ChatMessage] = relationship(back_populates="flags")
