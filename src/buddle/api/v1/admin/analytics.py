"""Admin analytics endpoints — /v1/admin/analytics/*.

네 가지 그래프 데이터를 제공합니다:
  1. tag-trends      — 화제 카테고리(태그)별 일별 유행 추이
  2. caution-summary — 유의 단어 잡지 현황 + 심각도별 윤리 알림 수
  3. knowledge-flow  — 지식 공간 시간당 투입/산출 흐름
  4. author-ratio    — 포스트·댓글의 유저 vs AI 생성 비율
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Query
from sqlalchemy import cast, func, select
from sqlalchemy.types import Date

from buddle.api.deps import DB, CurrentAdmin
from buddle.db.models.comment import Comment
from buddle.db.models.enums import AuthorKind
from buddle.db.models.ethics_alert import EthicsAlert
from buddle.db.models.knowledge_audit import KnowledgeAudit
from buddle.db.models.post import Post
from buddle.db.models.tag import PostTag, Tag

router = APIRouter(prefix="/analytics", tags=["admin:analytics"])


# ── 1. 화제 태그별 일별 유행 ─────────────────────────────────────────────


@router.get("/tag-trends", summary="일별 상위 태그 빈도 추이")
async def tag_trends(
    _: CurrentAdmin,
    db: DB,
    days: int = Query(default=7, ge=1, le=30),
    top_n: int = Query(default=8, ge=3, le=20),
) -> dict[str, object]:
    since = datetime.now(UTC) - timedelta(days=days)

    # 상위 태그 선정
    top_rows = (
        await db.execute(
            select(Tag.name, func.count(PostTag.post_id).label("c"))
            .join(PostTag, PostTag.tag_id == Tag.id)
            .join(Post, Post.id == PostTag.post_id)
            .where(Post.created_at >= since)
            .group_by(Tag.name)
            .order_by(func.count(PostTag.post_id).desc())
            .limit(top_n)
        )
    ).all()
    top_tags = [r[0] for r in top_rows]

    if not top_tags:
        # Match the populated branch's label count (days + 1, inclusive of today)
        # so the chart x-axis is consistent whether or not data exists.
        labels = [(since + timedelta(days=i)).strftime("%m-%d") for i in range(days + 1)]
        return {"labels": labels, "datasets": []}

    # 일별 × 태그 집계
    daily_rows = (
        await db.execute(
            select(
                cast(Post.created_at, Date).label("day"),
                Tag.name.label("tag"),
                func.count(PostTag.post_id).label("c"),
            )
            .join(PostTag, PostTag.post_id == Post.id)
            .join(Tag, Tag.id == PostTag.tag_id)
            .where(Post.created_at >= since, Tag.name.in_(top_tags))
            .group_by(cast(Post.created_at, Date), Tag.name)
            .order_by(cast(Post.created_at, Date))
        )
    ).all()

    # 날짜 레이블 생성
    date_labels = [(since + timedelta(days=i)).strftime("%m-%d") for i in range(days + 1)]
    date_keys = [(since + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(days + 1)]

    # 태그별 카운트 맵
    count_map: dict[str, dict[str, int]] = {t: {d: 0 for d in date_keys} for t in top_tags}
    for row in daily_rows:
        dk = str(row.day)
        if dk in count_map.get(row.tag, {}):
            count_map[row.tag][dk] = int(row.c)

    datasets = [{"tag": tag, "counts": [count_map[tag][d] for d in date_keys]} for tag in top_tags]

    return {"labels": date_labels, "datasets": datasets}


# ── 2. 유의 단어 잡지 현황 + 윤리 알림 ──────────────────────────────────


@router.get("/caution-summary", summary="유의 단어 카테고리별 현황 + 윤리 알림 심각도 분포")
async def caution_summary(
    _: CurrentAdmin,
    db: DB,
    days: int = Query(default=7, ge=1, le=90),
) -> dict[str, object]:
    from buddle.config import get_settings

    settings = get_settings()
    lexicon_data: dict[str, object] = {}

    # 잡지 JSON 읽기
    if settings.caution_lexicon_path:
        try:
            import pathlib

            raw = pathlib.Path(settings.caution_lexicon_path).read_text(encoding="utf-8")
            lexicon_data = json.loads(raw)
        except (OSError, json.JSONDecodeError):
            lexicon_data = {}

    raw_entries = lexicon_data.get("entries", [])
    entries: list[dict[str, str]] = raw_entries if isinstance(raw_entries, list) else []
    version: str = str(lexicon_data.get("version", "미설정"))

    # 카테고리별 집계
    cat_map: dict[str, list[str]] = {}
    for e in entries:
        cat = str(e.get("category", "general"))
        cat_map.setdefault(cat, []).append(str(e.get("word", "")))

    categories = [
        {"name": cat, "word_count": len(words), "sample_words": words[:5]}
        for cat, words in cat_map.items()
    ]

    # 윤리 알림 심각도 분포 (최근 N일)
    since = datetime.now(UTC) - timedelta(days=days)
    severity_rows = (
        await db.execute(
            select(EthicsAlert.severity, func.count(EthicsAlert.id).label("c"))
            .where(EthicsAlert.created_at >= since)
            .group_by(EthicsAlert.severity)
        )
    ).all()
    severity_dist = {str(r.severity): int(r.c) for r in severity_rows}

    # 일별 윤리 알림 추이
    daily_rows = (
        await db.execute(
            select(
                cast(EthicsAlert.created_at, Date).label("day"),
                func.count(EthicsAlert.id).label("c"),
            )
            .where(EthicsAlert.created_at >= since)
            .group_by(cast(EthicsAlert.created_at, Date))
            .order_by(cast(EthicsAlert.created_at, Date))
        )
    ).all()
    date_keys = [(since + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(days + 1)]
    date_labels = [(since + timedelta(days=i)).strftime("%m-%d") for i in range(days + 1)]
    daily_map = {str(r.day): int(r.c) for r in daily_rows}
    daily_alerts = [daily_map.get(d, 0) for d in date_keys]

    return {
        "lexicon_version": version,
        "total_words": len(entries),
        "categories": categories,
        "severity_distribution": severity_dist,
        "alert_trend_labels": date_labels,
        "alert_trend_counts": daily_alerts,
    }


# ── 3. 지식 공간 시간당 투입/산출 흐름 ──────────────────────────────────


@router.get("/knowledge-flow", summary="시간당 지식 공간 자료 투입(retain) vs 산출(synthesize)")
async def knowledge_flow(
    _: CurrentAdmin,
    db: DB,
    hours: int = Query(default=48, ge=6, le=168),
) -> dict[str, object]:
    since = datetime.now(UTC) - timedelta(hours=hours)

    rows = (
        await db.execute(
            select(KnowledgeAudit.action, KnowledgeAudit.created_at)
            .where(KnowledgeAudit.created_at >= since)
            .order_by(KnowledgeAudit.created_at)
        )
    ).all()

    # 시간 버킷 생성 (최대 48개)
    slot_count = min(hours, 48)
    slot_hours = hours // slot_count
    slots: list[datetime] = [since + timedelta(hours=i * slot_hours) for i in range(slot_count + 1)]
    labels = [s.strftime("%m-%d %H시") for s in slots[:-1]]

    fetched = [0] * slot_count
    produced = [0] * slot_count
    total_fetched = 0
    total_produced = 0

    for row in rows:
        action = str(row.action).lower()
        ts = row.created_at
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=UTC)
        elapsed = (ts - since).total_seconds() / 3600
        idx = min(int(elapsed / slot_hours), slot_count - 1)
        if any(k in action for k in ("retain", "extract", "consider", "fetch", "ingest")):
            fetched[idx] += 1
            total_fetched += 1
        elif any(k in action for k in ("synthes", "bundle", "produce", "emit")):
            produced[idx] += 1
            total_produced += 1

    return {
        "labels": labels,
        "fetched": fetched,
        "produced": produced,
        "total_fetched": total_fetched,
        "total_produced": total_produced,
        "window_hours": hours,
    }


# ── 4. 유저 vs AI 생성 비율 ──────────────────────────────────────────────


@router.get("/author-ratio", summary="포스트·댓글의 유저 대 AI 생성 비율")
async def author_ratio(
    _: CurrentAdmin,
    db: DB,
    days: int = Query(default=7, ge=1, le=30),
) -> dict[str, object]:
    since = datetime.now(UTC) - timedelta(days=days)

    # 전체 합계 — 포스트
    post_counts_rows = (
        await db.execute(
            select(Post.author_kind, func.count(Post.id).label("c"))
            .where(Post.created_at >= since)
            .group_by(Post.author_kind)
        )
    ).all()
    post_totals = {str(r.author_kind): int(r.c) for r in post_counts_rows}

    # 전체 합계 — 댓글
    comment_counts_rows = (
        await db.execute(
            select(Comment.author_kind, func.count(Comment.id).label("c"))
            .where(Comment.created_at >= since)
            .group_by(Comment.author_kind)
        )
    ).all()
    comment_totals = {str(r.author_kind): int(r.c) for r in comment_counts_rows}

    # 일별 추이 — 포스트 (human vs AI 합계)
    post_daily_rows = (
        await db.execute(
            select(
                cast(Post.created_at, Date).label("day"),
                Post.author_kind,
                func.count(Post.id).label("c"),
            )
            .where(Post.created_at >= since)
            .group_by(cast(Post.created_at, Date), Post.author_kind)
            .order_by(cast(Post.created_at, Date))
        )
    ).all()

    # 일별 추이 — 댓글
    comment_daily_rows = (
        await db.execute(
            select(
                cast(Comment.created_at, Date).label("day"),
                Comment.author_kind,
                func.count(Comment.id).label("c"),
            )
            .where(Comment.created_at >= since)
            .group_by(cast(Comment.created_at, Date), Comment.author_kind)
            .order_by(cast(Comment.created_at, Date))
        )
    ).all()

    date_keys = [(since + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(days + 1)]
    date_labels = [(since + timedelta(days=i)).strftime("%m-%d") for i in range(days + 1)]

    ai_kinds = {AuthorKind.PERSONA_AI.value, AuthorKind.EXTERNAL_AI.value, AuthorKind.BOT.value}

    def _split_daily(rows: Sequence[Any]) -> tuple[list[int], list[int]]:
        human_map: dict[str, int] = {d: 0 for d in date_keys}
        ai_map: dict[str, int] = {d: 0 for d in date_keys}
        for r in rows:
            dk = str(r.day)
            if dk not in human_map:
                continue
            kind = str(r.author_kind)
            if kind in ai_kinds:
                ai_map[dk] += int(r.c)
            else:
                human_map[dk] += int(r.c)
        return [human_map[d] for d in date_keys], [ai_map[d] for d in date_keys]

    post_human_trend, post_ai_trend = _split_daily(post_daily_rows)
    comment_human_trend, comment_ai_trend = _split_daily(comment_daily_rows)

    human_posts = post_totals.get(AuthorKind.HUMAN.value, 0)
    ai_posts = sum(post_totals.get(k, 0) for k in ai_kinds)
    human_comments = comment_totals.get(AuthorKind.HUMAN.value, 0)
    ai_comments = sum(comment_totals.get(k, 0) for k in ai_kinds)

    return {
        "labels": date_labels,
        "posts": {
            "human": human_posts,
            "ai": ai_posts,
            "detail": post_totals,
            "trend_human": post_human_trend,
            "trend_ai": post_ai_trend,
        },
        "comments": {
            "human": human_comments,
            "ai": ai_comments,
            "detail": comment_totals,
            "trend_human": comment_human_trend,
            "trend_ai": comment_ai_trend,
        },
    }
