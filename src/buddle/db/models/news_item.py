"""Collected news item — the DB 저장 step of the RSS pipeline.

    RSS 수집 → XML 파싱 → **DB 저장** → 중복 제거 → 알고리즘 분석 → 사용자 제공

Why a table (previously Redis-only): the guid UNIQUE constraint makes 중복
제거 a database guarantee instead of a TTL'd Redis set (which silently forgot
items whenever Redis restarted — observed twice in staging), and topic
extraction can aggregate over a real retention window. Only headline metadata
is stored (title/link/summary snippet) — the rights engine's default-deny
policy still applies to bodies, which are never collected.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Index, String, Text, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from buddle.db.base import Base


class NewsItem(Base):
    __tablename__ = "news_items"
    __table_args__ = (
        # 최근 N시간 화제 집계가 주요 읽기 경로 — 시간 역순 스캔용.
        Index("ix_news_items_published_at", "published_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    # RSS GUID가 있으면 그것, 없으면 URL 해시 — 어느 쪽이든 재수집 시 충돌해
    # ON CONFLICT DO NOTHING으로 걸러진다(중복 제거).
    guid: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    source: Mapped[str] = mapped_column(String(100), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # 알고리즘 분류 결과(수집 시 1회 계산) — 필터 질의는 이 컬럼으로.
    category: Mapped[str] = mapped_column(String(20), nullable=False, default="사회")
    scope: Mapped[str] = mapped_column(String(10), nullable=False, default="해외")
    region: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    published_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    stored_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
