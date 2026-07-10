"""News schemas — the rights-filtered public shape of a briefing.

These are the ONLY news fields exposed to regular users. The content-rights
engine's beta policy is default-deny for every outlet: title + link + outlet
name + our own 1–3 line factual gist (written in our words from the official
RSS snippet) + our tags. Internal pipeline fields (ekb_briefing, relevance,
stub) never leave the admin surface — see
docs/superpowers/specs/2026-06-28-content-rights-engine.md.
"""

from __future__ import annotations

from pydantic import BaseModel


class NewsBriefingOut(BaseModel):
    """One topic teaser: read our gist, follow the link for the article."""

    title: str
    url: str  # canonical link to the outlet — reading happens at the source
    source: str  # outlet name (attribution)
    gist_ko: str  # our own factual summary (not the outlet's wording)
    tags: list[str]
    # 출처 권리 등급: "kogl_type1"(공공누리 1유형 — 출처표시 시 인용·2차창작
    # 가능, 앱이 인용 추천 배지 표시) | "default_deny"(제목+링크+요약만).
    rights: str
    stored_at: int  # unix seconds — client renders relative time


class NewsDigestOut(BaseModel):
    """The mediator's combined cross-article digest (entirely our own text)."""

    text: str
    tags: list[str]
    count: int
    ts: int


class NewsTopicHeadline(BaseModel):
    """제목+링크+출처만 — 권리엔진 default-deny 하에서 안전한 최소 표면."""

    title: str
    url: str
    source: str


class NewsTopicOut(BaseModel):
    """알고리즘 집계 화제 하나 — 필터(범위·주제·위치)로 탐색된다."""

    name: str
    count: int  # 관련 기사 수
    sources: list[str]
    category: str  # 환경/교육/경제/정치/기술/사회
    scope: str  # 동네/시/도/전국/해외
    region: str  # 스코프가 지역일 때의 라벨(예: "성남", "강남구")
    headlines: list[NewsTopicHeadline]
    # 추세(M7): 포아송-감마 사후 + EWMA 방향으로 계산된 상승 확률과 라벨.
    trend: str = "유지"  # 상승|유지|하락
    p_rise: float = 0.0
