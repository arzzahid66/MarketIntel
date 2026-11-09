"""AI analyst persistence (Phase 4).

One table, and it does two jobs that must not be separated:

  * **It is the meter.** Plan limits (`ai.messages_per_day`, `ai.messages_per_hour`)
    are counted from these rows, server-side, on the request that is about to
    spend one. Counting in Redis would be faster and would lose the count on a
    flush - and a quota that resets when a cache restarts is not a quota.
  * **It is the audit trail.** Every answer records the question, the model, and
    the exact articles cited. "Not financial advice" is only defensible if what
    the analyst said, and what it said it from, can be produced later.

Answers are never reused across users. A cached answer would be a different
user's context leaking into this one's.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, uuid_pk


class AiMessage(Base):
    """One question and its answer. Also the row the quota counts."""

    __tablename__ = "ai_messages"
    __table_args__ = (
        # The quota query: "this user's messages since <instant>".
        Index("ix_ai_message_user_created", "user_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    question: Mapped[str] = mapped_column(Text, nullable=False)
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    #: The articles the answer was built from: id, title, publisher, source_url.
    #: Denormalised on purpose - a citation must still resolve after the feed
    #: item is pruned, or the audit trail has holes exactly where it matters.
    citations_json: Mapped[list[dict]] = mapped_column(JSONB, nullable=False, default=list)
    model: Mapped[str] = mapped_column(String(64), nullable=False)
    prompt_version: Mapped[int] = mapped_column(Integer, nullable=False)
    #: How many articles were retrieved before the model saw them.
    retrieved: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
