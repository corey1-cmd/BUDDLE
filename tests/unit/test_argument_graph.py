"""Argument graph — pure-layer unit tests (no DB, no network).

Locks the Kialo-style hierarchy: claim-rooted tree, dimension inference
(problem/cause/solution), ground/rebuttal parenting, evidence depth, and
determinism.
"""

from __future__ import annotations

import uuid

from buddle.ai.argument import (
    FlatUnit,
    GraphDimension,
    GraphNodeKind,
    build_graph_view,
    classify_dimension,
)


def _u(kind: str, stance: str, text: str, parent: uuid.UUID | None = None) -> FlatUnit:
    return FlatUnit(id=uuid.uuid4(), kind=kind, stance=stance, text=text, parent_unit_id=parent)


# ── dimension classification ────────────────────────────────────────────────


def test_classify_dimension_cause():
    assert classify_dimension("집값 때문에 출산율이 줄었다") is GraphDimension.CAUSE
    assert classify_dimension("this is due to high costs") is GraphDimension.CAUSE


def test_classify_dimension_solution():
    assert classify_dimension("주택 지원을 확대해야 한다") is GraphDimension.SOLUTION
    assert classify_dimension("we should introduce a policy") is GraphDimension.SOLUTION


def test_classify_dimension_problem():
    assert classify_dimension("출산율 감소가 심각한 문제다") is GraphDimension.PROBLEM


def test_classify_dimension_defaults_to_claim():
    assert classify_dimension("나는 고양이를 좋아한다") is GraphDimension.CLAIM


def test_cause_precedence_over_solution():
    # 인과 표지가 해결책 표지보다 특이적 → cause 우선.
    assert classify_dimension("지원이 필요한 이유는 비용 때문이다") is GraphDimension.CAUSE


# ── graph structure ─────────────────────────────────────────────────────────


def test_empty_topic_yields_empty_graph():
    gv = build_graph_view(uuid.uuid4(), [])
    assert gv.claim_count == 0
    assert gv.nodes == []
    assert "주장" in gv.summary  # 안내 문구


def test_claims_are_roots():
    c = _u("claim", "pro", "주택 지원을 확대해야 한다")
    gv = build_graph_view(uuid.uuid4(), [c])
    roots = [n for n in gv.nodes if n.parent_id is None]
    assert len(roots) == 1
    assert roots[0].kind is GraphNodeKind.CLAIM
    assert roots[0].depth == 0
    assert roots[0].dimension is GraphDimension.SOLUTION


def test_ground_attaches_to_parent_claim():
    c = _u("claim", "pro", "주택 지원을 확대해야 한다")
    g = _u("ground", "pro", "지원 후 출산율이 올랐다", parent=c.id)
    gv = build_graph_view(uuid.uuid4(), [c, g])
    gnode = next(n for n in gv.nodes if n.kind is GraphNodeKind.GROUND)
    assert gnode.parent_id == str(c.id)
    assert gnode.depth == 1


def test_orphan_ground_falls_back_to_first_claim():
    c = _u("claim", "pro", "첫 주장")
    g = _u("ground", "pro", "부모 없는 근거", parent=None)
    gv = build_graph_view(uuid.uuid4(), [c, g])
    gnode = next(n for n in gv.nodes if n.kind is GraphNodeKind.GROUND)
    assert gnode.parent_id == str(c.id)  # 고아 방지


def test_rebuttal_on_ground_is_depth_2():
    c = _u("claim", "pro", "주장")
    g = _u("ground", "pro", "근거", parent=c.id)
    r = _u("rebuttal", "con", "그 근거는 단기효과일 뿐", parent=g.id)
    gv = build_graph_view(uuid.uuid4(), [c, g, r])
    rnode = next(n for n in gv.nodes if n.kind is GraphNodeKind.REBUTTAL)
    assert rnode.depth == 2
    assert rnode.parent_id == str(g.id)
    assert rnode.stance == "con"


def test_rebuttal_on_claim_is_depth_1():
    c = _u("claim", "pro", "주장")
    r = _u("rebuttal", "con", "그 주장은 틀렸다", parent=c.id)
    gv = build_graph_view(uuid.uuid4(), [c, r])
    rnode = next(n for n in gv.nodes if n.kind is GraphNodeKind.REBUTTAL)
    assert rnode.depth == 1
    assert rnode.parent_id == str(c.id)


def test_question_is_parentless_root():
    c = _u("claim", "pro", "주장")
    q = _u("question", "neutral", "정말 그럴까?")
    gv = build_graph_view(uuid.uuid4(), [c, q])
    qnode = next(n for n in gv.nodes if n.kind is GraphNodeKind.QUESTION)
    assert qnode.parent_id is None
    assert qnode.depth == 0


def test_weight_counts_children():
    c = _u("claim", "pro", "주장")
    g1 = _u("ground", "pro", "근거1", parent=c.id)
    g2 = _u("ground", "pro", "근거2", parent=c.id)
    gv = build_graph_view(uuid.uuid4(), [c, g1, g2])
    cnode = next(n for n in gv.nodes if n.kind is GraphNodeKind.CLAIM)
    assert cnode.weight == 3  # self + 2 grounds


def test_deterministic_ordering():
    units = [
        _u("claim", "pro", "주장 A"),
        _u("claim", "con", "주장 B"),
        _u("ground", "pro", "근거"),
    ]
    tag = uuid.uuid4()
    a = build_graph_view(tag, list(units))
    b = build_graph_view(tag, list(units))
    assert [n.id for n in a.nodes] == [n.id for n in b.nodes]


def test_counts_in_summary():
    c = _u("claim", "pro", "주장")
    g = _u("ground", "pro", "근거", parent=c.id)
    r = _u("rebuttal", "con", "반박", parent=c.id)
    gv = build_graph_view(uuid.uuid4(), [c, g, r])
    assert gv.claim_count == 1
    assert gv.ground_count == 1
    assert gv.rebuttal_count == 1
    assert "주장 1개" in gv.summary
