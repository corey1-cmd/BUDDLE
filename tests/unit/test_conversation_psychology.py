"""Conversation psychology — pure-layer unit tests (no DB, no network).

Locks the two theory commitments:
  * Social Penetration Theory — level stages, hysteresis, Current Level + 1.
  * Gottman emotional bank account — positive:negative 5:1 weighting,
    self-disclosure / reciprocity deposits, per-turn clamp.
Plus situation mapping, recency-biased mood, and conditional principle
selection (the antidote to pre-planned repeated empathy).
"""

from __future__ import annotations

from buddle.ai.affect.perception import Valence
from buddle.ai.cognition.signals import Intent
from buddle.ai.conversation import (
    ConversationContext,
    ConversationSituation,
    Mood,
    RelationshipLevel,
    TurnAffect,
    affinity_delta,
    aggregate_mood,
    apply_delta,
    build_conversation_guidance,
    disclosure_target_level,
    level_for_score,
    situation_for,
)

# ── Gottman emotional bank account: 5:1 negativity bias ─────────────────────


def test_positive_is_small_deposit_negative_is_heavy_withdrawal():
    pos = affinity_delta(TurnAffect(Valence.POSITIVE, 0.0))
    neg = affinity_delta(TurnAffect(Valence.NEGATIVE, 0.0))
    assert pos > 0 and neg < 0
    # The magic ratio: a negative turn weighs ~5x a positive one.
    assert abs(neg) == abs(pos) * 5.0


def test_neutral_is_tiny_positive_presence():
    d = affinity_delta(TurnAffect(Valence.NEUTRAL, 0.0))
    assert 0 < d < affinity_delta(TurnAffect(Valence.POSITIVE, 0.0))


def test_intensity_scales_deposit():
    low = affinity_delta(TurnAffect(Valence.POSITIVE, 0.0))
    high = affinity_delta(TurnAffect(Valence.POSITIVE, 1.0))
    assert high > low


def test_self_disclosure_adds_deposit():
    base = affinity_delta(TurnAffect(Valence.POSITIVE, 0.3))
    with_disc = affinity_delta(TurnAffect(Valence.POSITIVE, 0.3), opened_disclosure=True)
    assert with_disc > base


def test_reciprocity_adds_deposit():
    base = affinity_delta(TurnAffect(Valence.POSITIVE, 0.3))
    with_recip = affinity_delta(TurnAffect(Valence.POSITIVE, 0.3), is_reciprocity=True)
    assert with_recip > base


def test_per_turn_delta_is_clamped():
    # Even a maximally intense negative turn can't swing more than the clamp.
    neg = affinity_delta(TurnAffect(Valence.NEGATIVE, 1.0))
    assert neg >= -(1.2 * 3.0) - 1e-9


def test_gains_shrink_at_higher_levels_losses_do_not():
    """SPT: penetration fast early, slow late — but trust is easy to lose."""
    gain_lvl0 = affinity_delta(TurnAffect(Valence.POSITIVE, 0.5), current_level=0)
    gain_lvl3 = affinity_delta(TurnAffect(Valence.POSITIVE, 0.5), current_level=3)
    assert gain_lvl3 < gain_lvl0
    loss_lvl0 = affinity_delta(TurnAffect(Valence.NEGATIVE, 0.5), current_level=0)
    loss_lvl3 = affinity_delta(TurnAffect(Valence.NEGATIVE, 0.5), current_level=3)
    assert loss_lvl0 == loss_lvl3  # withdrawals not shrunk


def test_score_clamped_to_domain():
    assert apply_delta(99.0, 50.0) == 100.0
    assert apply_delta(1.0, -50.0) == 0.0


# ── Social Penetration Theory: levels + hysteresis ──────────────────────────


def test_level_mapping_across_score_range():
    assert level_for_score(0.0) == RelationshipLevel.ORIENTATION
    assert level_for_score(10.0) == RelationshipLevel.EXPLORATORY
    assert level_for_score(30.0) == RelationshipLevel.AFFECTIVE
    assert level_for_score(50.0) == RelationshipLevel.STABLE
    assert level_for_score(80.0) == RelationshipLevel.INTIMATE


def test_upgrade_is_immediate():
    # crossing 22 from below jumps to AFFECTIVE at once.
    assert level_for_score(23.0, current_level=1) == RelationshipLevel.AFFECTIVE


def test_downgrade_requires_hysteresis():
    # At Lv2 (edge 22), a dip to 20 holds (within 4-point hysteresis)...
    assert level_for_score(20.0, current_level=2) == RelationshipLevel.AFFECTIVE
    # ...but a real drop below 18 demotes.
    assert level_for_score(17.0, current_level=2) == RelationshipLevel.EXPLORATORY


def test_disclosure_target_is_level_plus_one_capped():
    assert disclosure_target_level(0) == 1
    assert disclosure_target_level(2) == 3
    assert disclosure_target_level(4) == 4  # capped at INTIMATE


# ── Situation mapping (reuses EKB Intent) ───────────────────────────────────


def test_situation_from_intent():
    assert (
        situation_for(Intent.SEEK_SUPPORT, valence=Valence.NEGATIVE)
        is ConversationSituation.EMPATHIC
    )
    assert (
        situation_for(Intent.ASK_INFO, valence=Valence.NEUTRAL) is ConversationSituation.OBJECTIVE
    )
    assert (
        situation_for(Intent.REFLECT, valence=Valence.NEUTRAL) is ConversationSituation.REFLECTIVE
    )
    assert (
        situation_for(Intent.MAKE_CONVERSATION, valence=Valence.NEUTRAL)
        is ConversationSituation.SOCIAL
    )


def test_neutral_news_is_social_not_empathic():
    assert situation_for(Intent.SHARE_NEWS, valence=Valence.NEUTRAL) is ConversationSituation.SOCIAL
    assert (
        situation_for(Intent.SHARE_NEWS, valence=Valence.POSITIVE) is ConversationSituation.EMPATHIC
    )


# ── Mood aggregation (recency-biased working set) ───────────────────────────


def test_mood_empty_window_is_neutral():
    m = aggregate_mood([])
    assert m.valence == 0.0 and m.energy == 0.0


def test_mood_is_recency_biased():
    # Opens positive, just turned negative → recent negative dominates.
    window = [
        TurnAffect(Valence.POSITIVE, 0.8),
        TurnAffect(Valence.POSITIVE, 0.8),
        TurnAffect(Valence.NEGATIVE, 0.9),
    ]
    m = aggregate_mood(window)
    assert m.valence < 0.5  # pulled down by the recent negative turn


def test_mood_energy_tracks_intensity():
    calm = aggregate_mood([TurnAffect(Valence.NEUTRAL, 0.05)])
    assert calm.label == "차분함"


# ── Principle selection: conditional, not scripted ──────────────────────────


def _ctx(**kw) -> ConversationContext:
    base = dict(
        situation=ConversationSituation.SOCIAL,
        mood=Mood(0.0, 0.3),
        relationship_level=0,
    )
    base.update(kw)
    return ConversationContext(**base)  # type: ignore[arg-type]


def test_empathic_situation_triggers_emotion_first():
    g = build_conversation_guidance(_ctx(situation=ConversationSituation.EMPATHIC))
    assert "공감" in g and "조언" in g


def test_objective_situation_allows_direct_facts():
    g = build_conversation_guidance(_ctx(situation=ConversationSituation.OBJECTIVE))
    assert "명확히" in g


def test_reflective_situation_allows_silence_and_reverse_question():
    g = build_conversation_guidance(_ctx(situation=ConversationSituation.REFLECTIVE))
    assert "역질문" in g


def test_depth_guidance_tracks_level():
    g0 = build_conversation_guidance(_ctx(relationship_level=0))
    g3 = build_conversation_guidance(_ctx(relationship_level=3))
    assert "Lv0" in g0 and "Lv3" in g3


def test_energy_matching_present_for_calm_mood():
    g = build_conversation_guidance(_ctx(mood=Mood(0.0, 0.05)))
    assert "차분" in g


def test_awkwardness_normalized_only_at_level_zero():
    g0 = build_conversation_guidance(_ctx(relationship_level=0))
    g2 = build_conversation_guidance(_ctx(relationship_level=2))
    assert "어색함을 허용" in g0
    assert "어색함을 허용" not in g2


def test_stepping_stone_only_on_topic_shift():
    g_shift = build_conversation_guidance(_ctx(is_topic_shift=True, window_topics=("산책", "날씨")))
    g_no_shift = build_conversation_guidance(_ctx(is_topic_shift=False))
    assert "이어지는" in g_shift
    assert "점프" not in g_no_shift


def test_interest_probe_only_when_interest_mentioned():
    g = build_conversation_guidance(_ctx(user_mentioned_interest=True))
    assert "왜/어떻게" in g


# ── Principles 11-21 (extended framework) ───────────────────────────────────


def test_principle_11_need_behind_request():
    g = build_conversation_guidance(_ctx(surface_request_with_distress=True))
    assert "욕구에 반응" in g


def test_principle_12_recover_lost_moments():
    g = build_conversation_guidance(_ctx(dangling_thread="이사 준비"))
    assert "이사 준비" in g and "연결감" in g


def test_principle_12_absent_when_no_thread():
    g = build_conversation_guidance(_ctx(dangling_thread=None))
    assert "답을 받지 못하고" not in g


def test_principle_14_17_escape_and_load():
    g = build_conversation_guidance(_ctx(persona_offering_choice=True))
    assert "거절할 여지" in g and "좁혀" in g


def test_principle_15_design_ending():
    g = build_conversation_guidance(_ctx(winding_down=True))
    assert "마지막 순간" in g


def test_principle_15_absent_when_not_winding_down():
    g = build_conversation_guidance(_ctx(winding_down=False))
    assert "마지막 순간" not in g


def test_principle_19_window_when_saying_no():
    g = build_conversation_guidance(_ctx(declining=True))
    assert "창문" in g


def test_principles_13_21_present_early_relationship():
    g = build_conversation_guidance(_ctx(relationship_level=0))
    assert "농담은 상대가 아니라 자신에게로" in g


def test_principles_13_21_absent_deep_relationship():
    g = build_conversation_guidance(_ctx(relationship_level=3))
    assert "농담은 상대가 아니라 자신에게로" not in g


def test_principle_8_strengthened_with_bandwidth():
    # calm mood now also advises shorter length (Principle 20).
    g = build_conversation_guidance(_ctx(mood=Mood(0.0, 0.05)))
    assert "소화할 만큼만 짧게" in g


# ── detectors (deterministic heuristics) ────────────────────────────────────


def test_detect_distress():
    from buddle.ai.conversation import detect_distress

    assert detect_distress("요즘 너무 힘들어")
    assert detect_distress("I feel so lonely")
    assert not detect_distress("오늘 날씨 좋네")


def test_is_request():
    from buddle.ai.conversation import is_request

    assert is_request("어떻게 해야 할까?")
    assert is_request("추천 좀 해줘")
    assert is_request("이거 맞아?")  # ends with ?
    assert not is_request("그냥 산책했어")


def test_detect_winding_down():
    from buddle.ai.conversation import detect_winding_down

    assert detect_winding_down("이만 자야겠다")
    assert detect_winding_down("ㅇㅇ")  # short closer
    assert not detect_winding_down("그래서 어떻게 생각해?")


def test_detect_decline_needed():
    from buddle.ai.conversation import detect_decline_needed

    assert detect_decline_needed("내일 만나줘")
    assert detect_decline_needed("약속해줘")
    assert not detect_decline_needed("오늘 뭐 했어?")
