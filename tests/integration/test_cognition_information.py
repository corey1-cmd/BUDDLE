"""EKB Stage A (Information Processing) tests — pure, no DB.

Validates the five sub-stages (exposure/attention/comprehension/acceptance/
retention), intent classification, and the bias-safety contract (depends only
on the current message).
"""

from __future__ import annotations

from buddle.ai.cognition import process_information
from buddle.ai.cognition.signals import Intent

# ── Exposure (language detection) ────────────────────────────────────────


def test_exposure_detects_korean():
    r = process_information("안녕하세요 반갑습니다")
    assert r.language == "ko"
    assert r.raw_len > 0


def test_exposure_detects_english():
    r = process_information("hello there friend")
    assert r.language == "en"


def test_exposure_detects_mixed():
    r = process_information("이거 API 호출 어떻게 해?")
    assert r.language == "mixed"


# ── Attention (selective filter) ─────────────────────────────────────────


def test_attention_extracts_salient_tokens_drops_stopwords():
    r = process_information("나는 그 영화를 정말 좋아해")
    # stopwords like 나/그/를 should be filtered; content words kept
    assert "영화" in r.attention.salient_tokens or "정말" in r.attention.salient_tokens
    assert "그" not in r.attention.salient_tokens


def test_attention_caps_salient_tokens():
    r = process_information(" ".join(f"단어{i}" for i in range(50)))
    assert len(r.attention.salient_tokens) <= 12


def test_attention_flags_question():
    r = process_information("이거 뭐야?")
    assert r.attention.is_question


def test_attention_flags_request():
    r = process_information("이 코드 좀 고쳐줘")
    assert r.attention.is_request


def test_attention_flags_urgency():
    r = process_information("급해 빨리 도와줘")
    assert r.attention.is_urgent


# ── Comprehension (intent) ───────────────────────────────────────────────


def test_intent_share_news():
    assert process_information("나 시험 합격했어!").intent == Intent.SHARE_NEWS


def test_intent_seek_support():
    assert process_information("너무 외롭고 힘들어").intent == Intent.SEEK_SUPPORT


def test_intent_ask_info():
    assert process_information("이거 어떻게 동작해?").intent == Intent.ASK_INFO


def test_intent_request_action():
    assert process_information("이 버그 고쳐줘").intent == Intent.REQUEST_ACTION


def test_intent_reflect_for_empty_ish():
    assert process_information("음").intent == Intent.REFLECT


# ── Acceptance (clarity) ─────────────────────────────────────────────────


def test_acceptance_low_clarity_flags_clarification():
    r = process_information("어")
    assert r.clarity < 0.35
    assert r.needs_clarification


def test_acceptance_high_clarity_no_clarification():
    r = process_information("다음 주 화요일에 부산으로 여행을 가려고 하는데 맛집을 추천해줘")
    assert r.clarity > 0.6
    assert not r.needs_clarification


def test_acceptance_question_not_flagged_for_clarification():
    # a short question shouldn't be flagged as needing clarification
    r = process_information("왜?")
    assert not r.needs_clarification


# ── Retention (transfer to memory) ───────────────────────────────────────


def test_retention_summary_includes_intent():
    r = process_information("나 합격했어 정말 기뻐")
    assert "share_news" in r.retained_summary


def test_retention_marks_urgency():
    r = process_information("급해 지금 당장 도와줘 제발")
    assert "긴급" in r.retained_summary


def test_retention_salient_points_bounded():
    r = process_information(" ".join(f"내용{i}" for i in range(20)))
    assert len(r.salient_points) <= 6


# ── bias-safety contract ─────────────────────────────────────────────────


def test_identical_message_yields_identical_result():
    msg = "오늘 발표가 너무 떨려서 불안해"
    assert process_information(msg) == process_information(msg)


def test_process_signature_takes_only_text():
    import inspect

    params = list(inspect.signature(process_information).parameters)
    assert params == ["text"]
