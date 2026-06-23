"""Argument-AI RAG prompt — pure-layer unit tests (no DB, no network).

Locks the safety scaffolding (mandatory label, no-fabrication instruction) and
the mode-specific prompt assembly that grounds the AI in retrieved evidence.
"""

from __future__ import annotations

from buddle.ai.argument import (
    ChatContext,
    ChatMode,
    RetrievedUnit,
    build_chat_prompt,
    has_grounding,
)


def _ctx(mode, units=(), excerpt="재개발은 필요하다", summary=""):
    return ChatContext(
        mode=mode,
        post_excerpt=excerpt,
        units=tuple(units),
        author_profile_summary=summary,
    )


# ── mandatory safety label ──────────────────────────────────────────────────


def test_claim_prompt_has_not_the_person_label():
    p = build_chat_prompt(_ctx(ChatMode.CLAIM))
    assert "본인이 아니며" in p
    assert "정체성" in p


def test_author_prompt_has_reconstruction_label():
    p = build_chat_prompt(_ctx(ChatMode.AUTHOR))
    assert "재현" in p and "본인이 아닙니다" in p


def test_prompt_forbids_fabrication():
    p = build_chat_prompt(_ctx(ChatMode.CLAIM, units=[RetrievedUnit("근거", "ground", "neutral")]))
    assert "지어내지" in p or "단정하지" in p


# ── evidence grounding ──────────────────────────────────────────────────────


def test_retrieved_units_appear_in_prompt():
    units = [
        RetrievedUnit("노후 주택이 위험하다", "ground", "neutral"),
        RetrievedUnit("이주 대책이 없다", "rebuttal", "con"),
    ]
    p = build_chat_prompt(_ctx(ChatMode.CLAIM, units=units))
    assert "노후 주택이 위험하다" in p
    assert "이주 대책이 없다" in p


def test_unit_kind_labels_are_korean():
    p = build_chat_prompt(_ctx(ChatMode.CLAIM, units=[RetrievedUnit("X", "rebuttal", "con")]))
    assert "반박" in p


def test_author_profile_summary_only_in_author_mode():
    p_author = build_chat_prompt(_ctx(ChatMode.AUTHOR, summary="신중하고 분석적"))
    assert "신중하고 분석적" in p_author
    # claim mode ignores any profile summary
    p_claim = build_chat_prompt(_ctx(ChatMode.CLAIM, summary="신중하고 분석적"))
    assert "신중하고 분석적" not in p_claim


def test_post_excerpt_included():
    p = build_chat_prompt(_ctx(ChatMode.CLAIM, excerpt="도시 재개발 논쟁"))
    assert "도시 재개발 논쟁" in p


# ── grounding gate ──────────────────────────────────────────────────────────


def test_has_grounding_true_with_units_or_excerpt():
    assert has_grounding(_ctx(ChatMode.CLAIM, units=[RetrievedUnit("x", "claim", "pro")]))
    assert has_grounding(_ctx(ChatMode.CLAIM, excerpt="some text", units=[]))


def test_has_grounding_false_when_empty():
    assert not has_grounding(_ctx(ChatMode.CLAIM, excerpt="", units=[]))


def test_prompt_is_deterministic():
    c = _ctx(ChatMode.AUTHOR, units=[RetrievedUnit("a", "claim", "pro")], summary="s")
    assert build_chat_prompt(c) == build_chat_prompt(c)
