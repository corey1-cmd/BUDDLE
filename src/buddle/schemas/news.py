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
