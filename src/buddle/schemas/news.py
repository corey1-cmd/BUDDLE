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


class NewsEntityBrief(BaseModel):
    """화제 등장 인물·기관의 위키백과 배경지식 — 상세 페이지 전용.

    노출 시 위키백과 링크와 CC BY-SA 4.0 표기를 생략하지 않는다.
    """

    name: str
    summary: str
    url: str = ""
    thumbnail: str = ""


class NewsTopicHeadline(BaseModel):
    """제목+링크+출처+발행일 — 권리엔진 default-deny 하에서 안전한 최소 표면."""

    title: str
    url: str
    source: str
    date: str = ""  # YYYY-MM-DD (발행일 표기 — 출처는 절대 생략하지 않는다)


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
    # 화제 글(광장) id — 카드 탭 시 뉴스 링크가 아니라 좋아요·댓글·토론이 있는
    # 글 상세로 이동한다(레딧식). tick이 화제마다 멱등 생성.
    post_id: str | None = None
    # 사람이 읽는 카드 문안 — 문장형 제목("무슨 일이 일어났는가")·한 문장
    # 요약·표시 키워드(한국어). LLM 정제 또는 결정론 폴백(대표 헤드라인).
    title: str = ""
    summary: str = ""
    keywords: list[str] = []
    # 카드 상호작용 버튼용 — 화제 글의 실카운트(글 미생성 시 0).
    like_count: int = 0
    comment_count: int = 0
    # 재난·안전 긴급 공지 — 카드 '긴급' 뱃지.
    urgent: bool = False
    # 위키백과 배경지식(상세 페이지 '배경지식' 박스 전용).
    entity_briefs: list[NewsEntityBrief] = []
