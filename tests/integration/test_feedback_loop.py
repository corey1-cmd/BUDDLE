"""Part 3 feedback-loop tests — pure, no DB.

Verifies the guardrailed mediator feedback math: strong-signal gate, tiny
fixed step, hard clamp, safety asymmetry (reports pull down faster), the
small proactivity mapping, and that topic offsets fold into dialogue cognition
without distorting safety/character.
"""

from __future__ import annotations

from buddle.ai.cognition import PersonaDispositions, ResponseStrategy, run_cognition
from buddle.ai.mediator.feedback import (
    AFFINITY_CAP,
    MAX_STEP,
    SIGNAL_THRESHOLD,
    TopicReactions,
    affinity_delta,
    apply_affinity,
    proactivity_adjustment,
    raw_signal,
)

# ── raw signal ────────────────────────────────────────────────────────────


def test_likes_and_importance_are_positive():
    r = TopicReactions(topic="t", reads=10, likes=5, reports=0, importance=2.0)
    assert raw_signal(r) > 0


def test_reports_are_negative_and_dominant():
    r = TopicReactions(topic="t", reads=5, likes=2, reports=5, importance=0.0)
    assert raw_signal(r) < 0


# ── strong-signal gate ─────────────────────────────────────────────────────


def test_weak_signal_ignored():
    r = TopicReactions(topic="t", reads=1, likes=0, reports=0, importance=0.0)
    assert abs(raw_signal(r)) < SIGNAL_THRESHOLD
    assert affinity_delta(r) == 0.0


def test_strong_positive_takes_one_step_up():
    r = TopicReactions(topic="t", reads=100, likes=20, reports=0, importance=5.0)
    assert affinity_delta(r) == MAX_STEP


def test_negative_pulls_down_faster_than_up():
    # safety asymmetry: a report-heavy topic moves down by more than MAX_STEP
    r = TopicReactions(topic="t", reads=5, likes=0, reports=5, importance=0.0)
    assert affinity_delta(r) < 0
    assert affinity_delta(r) <= -MAX_STEP


# ── step size + clamp ───────────────────────────────────────────────────────


def test_single_update_is_bounded_by_step():
    r = TopicReactions(topic="t", reads=1000, likes=500, reports=0, importance=50.0)
    # even a viral post only moves affinity by one step
    assert apply_affinity(0.0, r) == MAX_STEP


def test_repeated_positive_clamped_to_cap():
    r = TopicReactions(topic="t", reads=100, likes=20, reports=0, importance=5.0)
    v = 0.0
    for _ in range(50):
        v = apply_affinity(v, r)
    assert v <= AFFINITY_CAP
    assert v == AFFINITY_CAP  # saturates exactly at the cap


def test_repeated_negative_clamped_to_floor():
    r = TopicReactions(topic="t", reads=5, likes=0, reports=10, importance=0.0)
    v = 0.0
    for _ in range(50):
        v = apply_affinity(v, r)
    assert v >= -AFFINITY_CAP


# ── proactivity mapping ─────────────────────────────────────────────────────


def test_proactivity_offset_is_small():
    # max affinity maps to a small proactivity offset (~0.1), not a big swing
    assert abs(proactivity_adjustment(AFFINITY_CAP)) <= 0.11
    assert abs(proactivity_adjustment(-AFFINITY_CAP)) <= 0.11


def test_zero_affinity_zero_offset():
    assert proactivity_adjustment(0.0) == 0.0


# ── dispositions offset (bounded, only proactivity) ─────────────────────────


def test_dispositions_offset_clamped_and_isolated():
    d = PersonaDispositions(warmth=0.7, informativeness=0.6, proactivity=0.95)
    d2 = d.with_proactivity_offset(0.5)  # would exceed 1.0
    assert d2.proactivity == 1.0  # clamped
    # other axes untouched
    assert d2.warmth == d.warmth
    assert d2.informativeness == d.informativeness


def test_dispositions_offset_floor():
    d = PersonaDispositions(proactivity=0.05)
    d2 = d.with_proactivity_offset(-0.5)
    assert d2.proactivity == 0.0


# ── cognition integration ───────────────────────────────────────────────────


def test_topic_offset_folds_into_cognition_safely():
    # a matching topic offset shouldn't change a clear intent's strategy class
    _, dec_no, _ = run_cognition("이거 어떻게 해?")
    _, dec_off, _ = run_cognition("이거 어떻게 해?", topic_offsets={"이거": 0.1})
    # both should still INFORM (offset only nudges proactivity, not safety/intent)
    assert dec_no.chosen == dec_off.chosen == ResponseStrategy.INFORM


def test_offset_does_not_override_safety():
    # even with a positive offset on a topic, a self-harm message stays COMFORT
    _, dec, _ = run_cognition("죽고싶어 너무 힘들어", topic_offsets={"죽고싶어": 0.1})
    assert dec.chosen == ResponseStrategy.COMFORT


def test_no_offsets_is_noop():
    _, dec_a, _ = run_cognition("오늘 뭐하지")
    _, dec_b, _ = run_cognition("오늘 뭐하지", topic_offsets=None)
    assert dec_a.chosen == dec_b.chosen
