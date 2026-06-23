"""Argument-AI retrieval → prompt context — pure layer (no I/O, no LLM).

RAG (Lewis et al. 2020): condition generation on retrieved evidence. This
module does NOT do the retrieval (that's I/O, in the service); it takes already
-retrieved units and assembles the system-prompt context, with the mandatory
safety scaffolding baked in:

  1. explicit label — "이 대화는 글쓴이의 공개 글로 구성한 AI 재현이며 본인이
     아닙니다" (also pinned in the UI).
  2. no assertions beyond context — don't state, as the author's position,
     anything not grounded in the retrieved evidence.
  3. (leukocyte gate runs separately, in the WS handler.)

Deterministic and offline: the stub persona backend produces a sensible reply
from this context; a real model slots in behind the same prompt.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

_MAX_CONTEXT_UNITS = 8
_MAX_UNIT_CHARS = 240


class ChatMode(StrEnum):
    """Which AI the user is talking to."""

    CLAIM = "claim"  # 주장 AI — one post's argument, deepened
    AUTHOR = "author"  # 인물 AI — the author's public thinking, reconstructed


@dataclass(frozen=True, slots=True)
class RetrievedUnit:
    """One retrieved piece of evidence (an argument unit or post excerpt)."""

    text: str
    kind: str  # claim / ground / rebuttal / question / post
    stance: str  # pro / con / neutral


@dataclass(frozen=True, slots=True)
class ChatContext:
    """Everything the prompt builder needs for one argument-AI turn."""

    mode: ChatMode
    post_excerpt: str
    units: tuple[RetrievedUnit, ...]
    author_profile_summary: str = ""  # only for AUTHOR mode, opt-in public


_LABEL_CLAIM = (
    "이 대화는 어떤 게시글의 '주장'을 공개된 내용만으로 구성한 AI입니다. "
    "글쓴이 본인이 아니며, 아래 근거 밖의 내용을 사실인 양 단정하지 않습니다."
)
_LABEL_AUTHOR = (
    "이 대화는 글쓴이가 공개한 글로 구성한 AI 재현이며 글쓴이 본인이 아닙니다. "
    "아래 공개 근거 밖의 생각이나 사실을 그 사람의 입장인 양 단정하지 않습니다."
)


def build_chat_prompt(ctx: ChatContext) -> str:
    """Assemble the argument-AI system prompt with safety scaffolding."""
    label = _LABEL_AUTHOR if ctx.mode == ChatMode.AUTHOR else _LABEL_CLAIM
    lines: list[str] = [f"[정체성 — 반드시 지킬 것]\n{label}"]

    if ctx.post_excerpt:
        lines.append(f"[대화의 바탕이 된 글]\n{ctx.post_excerpt[:_MAX_UNIT_CHARS]}")

    if ctx.units:
        lines.append("[공개 근거 — 이 범위 안에서만 그 입장을 대변하세요]")
        for u in ctx.units[:_MAX_CONTEXT_UNITS]:
            tag = {
                "claim": "주장",
                "ground": "근거",
                "rebuttal": "반박",
                "question": "질문",
                "post": "글",
            }.get(u.kind, "내용")
            lines.append(f"- ({tag}) {u.text[:_MAX_UNIT_CHARS]}")

    if ctx.mode == ChatMode.AUTHOR and ctx.author_profile_summary:
        lines.append(f"[글쓴이가 공개 동의한 성향 요약]\n{ctx.author_profile_summary}")

    lines.append(
        "[대화 방식]\n"
        "- 위 근거에 충실하게, 그 주장/사람의 관점에서 자연스럽게 답하세요.\n"
        "- 근거에 없는 질문을 받으면 '공개된 글에서는 그 부분까지는 확인되지 않는다'고 "
        "솔직히 말하고, 지어내지 마세요.\n"
        "- 정중하고 차분한 톤. 상대를 설득하기보다 그 입장을 이해하도록 돕습니다."
    )
    return "\n".join(lines)


def has_grounding(ctx: ChatContext) -> bool:
    """True if there's at least some retrieved evidence to ground the reply.

    The service uses this to decide whether a meaningful AI conversation is
    even possible (a post with no extractable arguments can't host one).
    """
    return bool(ctx.units) or bool(ctx.post_excerpt.strip())
