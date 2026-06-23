"""Layer B stage-1 pure-core tests — extraction, selection gate, topic edges.

All pure/deterministic, no DB, no external calls. Verifies the curation logic:
1..5 unit extraction, retain-vs-let-pass scoring, novelty/redundancy mapping,
and edge weight accumulation + decay.
"""

from __future__ import annotations

from buddle.ai.knowledge import (
    DEFAULT_MAX_UNITS,
    SelectionSignals,
    SelectionWeights,
    apply_delta,
    decayed,
    edge_delta,
    extract_units,
    is_dead,
    normalize_pair,
    novelty_from_similarity,
    proximity_from_distance,
    redundancy_from_count,
    retention_score,
    should_retain,
)

# ── extraction (1..5 units) ────────────────────────────────────────────────


def test_empty_text_yields_no_units():
    assert extract_units("") == []
    assert extract_units("   \n ") == []


def test_short_text_is_one_unit():
    units = extract_units("동네 산책 좋아")
    assert len(units) == 1
    assert units[0].gist == "동네 산책 좋아"


def test_multi_thought_capped_at_max():
    text = (
        "오늘 동네 산책했어. 날씨가 좋더라! 다음엔 강가로 가볼까? "
        "운동도 같이 하면 좋겠다. 사진도 찍고 싶어. 커피도 마시자. 책도 읽자."
    )
    units = extract_units(text)
    assert 1 <= len(units) <= DEFAULT_MAX_UNITS
    assert len(units) == DEFAULT_MAX_UNITS  # 7 segments -> capped at 5


def test_max_units_param_respected():
    text = (
        "첫번째 생각입니다. 두번째 생각입니다. 세번째 생각입니다. "
        "네번째 생각입니다. 다섯번째 생각입니다."
    )
    assert len(extract_units(text, max_units=3)) == 3


def test_extraction_deterministic():
    text = "생각 하나입니다. 생각 두울입니다. 생각 세엣입니다."
    assert [u.gist for u in extract_units(text)] == [u.gist for u in extract_units(text)]


def test_units_preserve_source_order():
    text = "첫째 문장이다. 둘째 문장이다. 셋째 문장이다."
    units = extract_units(text)
    spans = [u.span[0] for u in units]
    assert spans == sorted(spans)  # original order


# ── selection gate ──────────────────────────────────────────────────────────


def test_novel_important_read_is_retained():
    s = SelectionSignals(
        genuine_read=True, importance=0.6, novelty=0.8, topic_fit=0.5, redundancy=0.0
    )
    assert should_retain(s)


def test_redundant_is_let_pass():
    s = SelectionSignals(
        genuine_read=True, importance=0.2, novelty=0.1, topic_fit=0.3, redundancy=1.0
    )
    assert not should_retain(s)


def test_unread_trivial_is_let_pass():
    s = SelectionSignals(
        genuine_read=False, importance=0.0, novelty=0.2, topic_fit=0.1, redundancy=0.0
    )
    assert not should_retain(s)


def test_negative_importance_does_not_raise_score():
    pos = SelectionSignals(
        genuine_read=False, importance=0.0, novelty=0.0, topic_fit=0.0, redundancy=0.0
    )
    neg = SelectionSignals(
        genuine_read=False, importance=-0.9, novelty=0.0, topic_fit=0.0, redundancy=0.0
    )
    assert retention_score(neg) == retention_score(pos)  # negative clamped out


def test_redundancy_strictly_lowers_score():
    base = SelectionSignals(
        genuine_read=True, importance=0.5, novelty=0.7, topic_fit=0.5, redundancy=0.0
    )
    dup = SelectionSignals(
        genuine_read=True, importance=0.5, novelty=0.7, topic_fit=0.5, redundancy=0.8
    )
    assert retention_score(dup) < retention_score(base)


def test_threshold_is_tunable():
    s = SelectionSignals(
        genuine_read=True, importance=0.1, novelty=0.3, topic_fit=0.2, redundancy=0.0
    )
    strict = SelectionWeights(threshold=0.9)
    lenient = SelectionWeights(threshold=0.05)
    assert not should_retain(s, strict)
    assert should_retain(s, lenient)


def test_novelty_from_similarity_mapping():
    assert novelty_from_similarity(1.0) == 0.0  # identical -> no novelty
    assert novelty_from_similarity(0.0) == 1.0  # unrelated -> full novelty
    assert novelty_from_similarity(-0.5) == 1.0  # clamped


def test_redundancy_from_count_saturates():
    assert redundancy_from_count(0) == 0.0
    assert redundancy_from_count(3, saturation=3) == 1.0
    assert redundancy_from_count(10, saturation=3) == 1.0  # clamped
    assert 0.0 < redundancy_from_count(1, saturation=3) < 1.0


# ── topic edges ──────────────────────────────────────────────────────────────


def test_edge_delta_combines_signals():
    # co-occurrence (1.0) + proximity 0.8 * 0.5 = 1.4
    assert edge_delta(co_occurred=True, emb_proximity=0.8) == 1.4
    # proximity only
    assert edge_delta(co_occurred=False, emb_proximity=0.6) == 0.3


def test_edge_proximity_clamped():
    assert edge_delta(co_occurred=False, emb_proximity=5.0) == 0.5  # prox clamps to 1


def test_edge_accumulates_and_decays():
    w = apply_delta(0.0, edge_delta(co_occurred=True, emb_proximity=0.0))  # 1.0
    assert w == 1.0
    d = decayed(w, 5)
    assert d < w  # decayed
    assert decayed(w, 0) == w  # no ticks, no change


def test_edge_dies_below_floor():
    assert is_dead(0.03)
    assert not is_dead(0.5)


def test_proximity_from_distance():
    assert proximity_from_distance(0.0) == 1.0  # identical
    assert proximity_from_distance(1.0) == 0.0  # orthogonal
    assert proximity_from_distance(2.0) == 0.0  # opposite, clamped


def test_normalize_pair_is_symmetric():
    assert normalize_pair("산책", "운동") == normalize_pair("운동", "산책")
