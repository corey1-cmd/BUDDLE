"""User profile — pure-layer unit tests (no DB, no network).

Locks the three epistemics commitments: bounded updates (Fleeson: one
utterance ≤ η shift), soft signals (moderate, capped, None when no evidence),
and saturating confidence that downstream layers must gate on.
"""

from __future__ import annotations

from buddle.ai.profile import (
    ETA,
    centroid_update,
    confidence_from_evidence,
    estimate_trait_signals,
    ewma_update,
)

# ── EWMA: the Fleeson guard ────────────────────────────────────────────────


def test_ewma_moves_toward_observation():
    assert ewma_update(0.5, 1.0) > 0.5
    assert ewma_update(0.5, 0.0) < 0.5


def test_single_observation_shift_bounded_by_eta():
    """A single message can never flip a trait — max shift is η·|obs−cur|."""
    assert abs(ewma_update(0.5, 1.0) - 0.5) <= ETA + 1e-9
    assert abs(ewma_update(0.0, 1.0) - 0.0) <= ETA + 1e-9


def test_ewma_clamps_out_of_range_inputs():
    assert 0.0 <= ewma_update(-3.0, 9.0) <= 1.0
    assert 0.0 <= ewma_update(2.0, -2.0) <= 1.0


# ── confidence: saturating, monotonic ──────────────────────────────────────


def test_confidence_zero_without_evidence():
    assert confidence_from_evidence(0) == 0.0


def test_confidence_monotonic_and_calibrated():
    values = [confidence_from_evidence(n) for n in (1, 10, 30, 100)]
    assert values == sorted(values)
    assert abs(values[2] - 0.6321) < 1e-3  # 1 − 1/e at n = 30
    assert values[-1] < 1.0  # inference never reaches certainty


# ── trait signals: soft, capped, evidence-or-None ──────────────────────────


def test_openness_signal_from_curiosity_text():
    s = estimate_trait_signals("새로운 전시가 궁금해서 보러 가고 싶어")
    assert s.o is not None and 0.5 < s.o <= 0.85


def test_neuroticism_signal_from_anxiety_text():
    s = estimate_trait_signals("요즘 너무 불안하고 걱정이 많아서 힘들어")
    assert s.n is not None and s.n <= 0.85


def test_neutral_text_yields_no_evidence():
    s = estimate_trait_signals("내일 점심에 김밥 먹을까 한다")
    assert not s.any()


def test_absence_is_not_a_low_score():
    """No markers → None, never a numeric low — silence isn't evidence."""
    s = estimate_trait_signals("오늘 회의는 3시에 시작한다")
    assert s.e is None and s.o is None


def test_signals_are_deterministic():
    text = "친구들 모임에서 신나게 놀았어, 고마운 사람들이야"
    assert estimate_trait_signals(text) == estimate_trait_signals(text)


def test_signal_capped_at_085():
    text = "불안 걱정 초조 스트레스 짜증 우울 두렵 무섭 힘들 예민"
    s = estimate_trait_signals(text)
    assert s.n is not None and s.n <= 0.85


# ── interest centroid ──────────────────────────────────────────────────────


def test_centroid_first_observation_initializes():
    assert centroid_update(None, [1.0, 0.0, 0.5]) == [1.0, 0.0, 0.5]


def test_centroid_moves_toward_new_embedding_boundedly():
    cur = [0.0, 0.0]
    new = centroid_update(cur, [1.0, 1.0])
    assert new == [ETA, ETA]  # exactly η of the way there


def test_centroid_dimension_mismatch_resets():
    assert centroid_update([0.5], [1.0, 0.0]) == [1.0, 0.0]
