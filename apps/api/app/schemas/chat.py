"""Chat request and response shapes."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class ChatRoomOut(BaseModel):
    slug: str
    name: str
    description: str


class ChatMessageOut(BaseModel):
    id: str
    body: str
    author: str
    author_id: str
    created_at: datetime
    #: Only ever true for the author's own message or for a moderator - an
    #: ordinary reader is not shown hidden posts at all.
    is_hidden: bool
    hidden_reason: str | None
    flags: int
    #: Moderator-only. Null for everyone else, so the screen's workings are not
    #: published to the people trying to get around it.
    spam_score: float | None = None
    spam_label: str | None = None


class ChatHistoryOut(BaseModel):
    server_time: datetime
    room: ChatRoomOut
    messages: list[ChatMessageOut]
    #: Whether this viewer's plan lets them post. Read-only viewers still see
    #: the room; the composer shows an upgrade prompt instead of an input.
    can_post: bool


class PostMessageIn(BaseModel):
    body: str = Field(min_length=1, max_length=2000)


class PostMessageOut(BaseModel):
    message: ChatMessageOut
    #: True when the spam screen hid it on arrival. Said plainly rather than
    #: shadow-banning, which teaches people the product is broken.
    auto_hidden: bool


class FlagIn(BaseModel):
    reason: str | None = Field(default=None, max_length=200)


class FlagOut(BaseModel):
    flags: int


class ModerateIn(BaseModel):
    hidden: bool
    reason: str | None = Field(default=None, max_length=500)
