"""Post schemas — create, read, feed items."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from buddle.db.models.enums import PostVisibility


class PostCreate(BaseModel):
    persona_id: uuid.UUID
    content_raw: str = Field(min_length=1, max_length=8000)
    visibility: PostVisibility


class PersonaBrief(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    model_key: str


class TagName(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str


class PostRead(BaseModel):
    """A post returned to its owner (includes raw content)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    source_persona: PersonaBrief | None
    content_raw: str
    content_transformed: str
    visibility: PostVisibility
    is_suppressed: bool
    tags: list[TagName]
    created_at: datetime


class PostFeedItem(BaseModel):
    """A post in the public feed (no raw content exposure)."""

    id: uuid.UUID
    source_persona: PersonaBrief | None
    # 비인간 저자(뉴스 화제 글 등)의 표시 이름 — persona가 없을 때 클라이언트가
    # '익명' 대신 이 라벨을 보여준다.
    author_label: str | None = None
    content_transformed: str
    tags: list[TagName]
    importance: float  # normalized [-1, 1]
    created_at: datetime


class MyPostItem(BaseModel):
    """내 프로필의 글 한 줄 — 소유자 뷰(비공개·억제 상태 포함, 카운트 동반)."""

    id: uuid.UUID
    source_persona: PersonaBrief | None
    content_transformed: str
    visibility: PostVisibility
    is_suppressed: bool
    tags: list[TagName]
    like_count: int
    comment_count: int
    created_at: datetime


class MyPostsPage(BaseModel):
    """인스타식 프로필: 상단 통계(게시물·받은 좋아요·받은 댓글) + 글 목록."""

    items: list[MyPostItem]
    next_cursor: str | None
    post_count: int
    like_count: int
    comment_count: int


class FeedPage(BaseModel):
    items: list[PostFeedItem]
    next_cursor: str | None
