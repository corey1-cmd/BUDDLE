"""Argument mining — pure-layer unit tests (no DB, no network).

Locks the Toulmin-reduced extraction (Stab & Gurevych 2017 scheme) and the
deterministic clustering that powers the dashboard's conversation axes.
"""

from __future__ import annotations

from buddle.ai.argument import (
    ArgumentKind,
    ArgumentStance,
    choose_k,
    cluster_claims,
    cosine_distance,
    extract_arguments,
    representative_index,
)

# ── extraction: the 4-way Toulmin reduction ─────────────────────────────────


def test_extracts_claim_ground_rebuttal_question():
    units = extract_arguments(
        "재개발은 반드시 필요하다. 왜냐하면 노후 주택이 위험하기 때문이다. "
        "하지만 원주민 이주 대책이 없다. 정말 괜찮을까?"
    )
    kinds = [u.kind for u in units]
    assert ArgumentKind.CLAIM in kinds
    assert ArgumentKind.GROUND in kinds
    assert ArgumentKind.REBUTTAL in kinds
    assert ArgumentKind.QUESTION in kinds


def test_question_is_neutral():
    units = extract_arguments("이게 정말 최선일까?")
    assert units[0].kind is ArgumentKind.QUESTION
    assert units[0].stance is ArgumentStance.NEUTRAL


def test_rebuttal_leans_con():
    units = extract_arguments("하지만 그 방법은 위험하다.")
    assert units[0].kind is ArgumentKind.REBUTTAL
    assert units[0].stance is ArgumentStance.CON


def test_ground_with_incidental_risk_word_stays_neutral():
    """A supporting reason mentioning '위험' must not be misread as CON."""
    units = extract_arguments("이 정책이 필요하다. 왜냐하면 방치하면 위험하기 때문이다.")
    ground = next(u for u in units if u.kind is ArgumentKind.GROUND)
    assert ground.stance is ArgumentStance.NEUTRAL


def test_explicit_agreement_is_pro():
    units = extract_arguments("나는 이 제안에 찬성한다.")
    assert units[0].stance is ArgumentStance.PRO


def test_extraction_is_deterministic():
    text = "재개발은 필요하다. 왜냐하면 위험하기 때문이다. 하지만 대책이 없다."
    assert extract_arguments(text) == extract_arguments(text)


def test_empty_and_fragment_input():
    assert extract_arguments("") == []
    assert extract_arguments("   ") == []
    assert extract_arguments("ㅋ") == []


def test_extraction_caps_units():
    text = " ".join(f"주장{i}는 반드시 필요하다." for i in range(10))
    assert len(extract_arguments(text)) <= 6


def test_most_declaratives_are_claims():
    units = extract_arguments("교육이 중요하다. 환경도 지켜야 한다.")
    assert all(u.kind is ArgumentKind.CLAIM for u in units)


# ── clustering: deterministic conversation axes ─────────────────────────────


def test_cosine_distance_bounds():
    assert cosine_distance([1.0, 0.0], [1.0, 0.0]) == 0.0
    assert abs(cosine_distance([1.0, 0.0], [0.0, 1.0]) - 1.0) < 1e-9
    assert cosine_distance([0.0, 0.0], [1.0, 0.0]) == 1.0  # zero vector


def test_choose_k_scales_with_points_capped_at_5():
    assert choose_k(0) == 1
    assert choose_k(1) == 1
    assert choose_k(3) == 1
    assert choose_k(4) == 2
    assert choose_k(100) == 5  # cap


def test_clustering_separates_dissimilar_claims():
    # Two tight groups far apart → forced k=2 must split them cleanly.
    embs = [[1.0, 0.0, 0.0], [0.95, 0.05, 0.0], [0.0, 0.0, 1.0], [0.0, 0.1, 0.95]]
    clusters = cluster_claims(embs, k=2)
    assert len(clusters) == 2
    groups = {frozenset(c.member_indices) for c in clusters}
    assert frozenset({0, 1}) in groups
    assert frozenset({2, 3}) in groups


def test_clustering_is_deterministic():
    embs = [[1.0, 0.0], [0.5, 0.5], [0.0, 1.0], [0.9, 0.1], [0.1, 0.9]]
    a = [c.member_indices for c in cluster_claims(embs, k=2)]
    b = [c.member_indices for c in cluster_claims(embs, k=2)]
    assert a == b


def test_single_and_empty_clustering():
    assert cluster_claims([]) == []
    one = cluster_claims([[1.0, 0.0]])
    assert len(one) == 1 and one[0].member_indices == [0]


def test_clusters_ordered_largest_first():
    # group of 3 + group of 1; the larger axis should lead.
    embs = [[1.0, 0.0], [0.98, 0.02], [0.96, 0.04], [0.0, 1.0]]
    clusters = cluster_claims(embs, k=2)
    assert len(clusters[0].member_indices) >= len(clusters[1].member_indices)


def test_representative_is_closest_to_centroid():
    embs = [[1.0, 0.0], [0.9, 0.1], [0.0, 1.0]]
    clusters = cluster_claims(embs, k=1)
    rep = representative_index(clusters[0], embs)
    assert rep in (0, 1)  # one of the two similar vectors, not the outlier
