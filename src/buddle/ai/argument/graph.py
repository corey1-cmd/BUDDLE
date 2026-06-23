"""논증 그래프 (Argument Graph) — Kialo식 구조화 토론 트리.

설계 (사용자 인지 흐름 반영):
  사람은 **주장을 먼저** 떠올린다. 그래서 트리의 루트는 화제가 아니라 *주장*이다.
  주장 아래에 그 주장이 다루는 **차원**(문제 / 원인 / 해결책)을 달고,
  각 차원·주장에 대해 **근거 · 증거 · 반박**을 매단다.

      주장 (claim, 루트)
       ├─ [문제] 노드
       │   ├─ 근거 (pro ground)
       │   │   └─ 증거 (evidence)
       │   └─ 반박 (con rebuttal)
       ├─ [원인] 노드
       └─ [해결책] 노드

데이터 출처: 기존 ArgumentUnit (claim / ground / rebuttal / question) + parent_unit_id
트리. 이 모듈은 **순수 함수**다 — DB에서 읽은 평면 unit 리스트를 받아 화면이 그릴
계층 그래프(노드 + 부모참조)로 변환할 뿐, I/O·임베딩·랜덤이 없어 결정적이다.
SVG 좌표 계산은 프론트(논증 그래프 탭)가 담당한다 (opposition.py와 동일한 분담).

차원(dimension) 추론: 짧은 한국어/영어 텍스트에서 문제/원인/해결책을 키워드로
가볍게 분류한다. 정확도보다 *유용한 묶음*이 목적이며, 미상이면 "주장"으로 둔다.
값이 아니라 묶음을 만드는 용도이므로 오분류 비용이 낮다.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import StrEnum

__all__ = [
    "FlatUnit",
    "GraphDimension",
    "GraphNode",
    "GraphNodeKind",
    "GraphView",
    "build_graph_view",
    "classify_dimension",
]


class GraphDimension(StrEnum):
    """주장이 다루는 차원 — 문제→원인→해결책 흐름 (첨부 '구조 1')."""

    PROBLEM = "problem"      # 무엇이 문제인가
    CAUSE = "cause"          # 무엇이 원인인가
    SOLUTION = "solution"    # 어떻게 해결할 것인가
    CLAIM = "claim"          # 차원 미상 — 일반 주장


class GraphNodeKind(StrEnum):
    """그래프 노드의 역할."""

    CLAIM = "claim"          # 루트 주장 (사람이 먼저 떠올리는 것)
    DIMENSION = "dimension"  # 문제/원인/해결책 묶음 헤더
    GROUND = "ground"        # 근거 (주장을 떠받침)
    EVIDENCE = "evidence"    # 증거 (근거를 떠받침 — 근거의 자식)
    REBUTTAL = "rebuttal"    # 반박 (주장/근거를 공격)
    QUESTION = "question"    # 열린 질문


# ── 차원 분류 키워드 (가벼운 휴리스틱; 묶음 생성용) ──────────────────────────
_PROBLEM_KW = (
    "문제", "위험", "위협", "우려", "심각", "부족", "결핍", "악화", "피해",
    "problem", "risk", "threat", "concern", "harm", "crisis", "issue",
)
_CAUSE_KW = (
    "때문", "원인", "탓", "기인", "비롯", "유발", "이유", "배경",
    "because", "cause", "due to", "reason", "root", "driven by",
)
_SOLUTION_KW = (
    "해결", "방안", "대책", "도입", "확대", "강화", "개선", "지원",
    "해야", "필요", "제안", "추진", "정책",
    "solution", "should", "must", "propose", "introduce", "expand",
    "strengthen", "improve", "support", "fix", "policy",
)


def classify_dimension(text: str) -> GraphDimension:
    """짧은 주장 텍스트를 문제/원인/해결책/일반으로 분류 (결정적, 휴리스틱).

    우선순위: 원인(인과 표지가 가장 특이적) → 해결책 → 문제 → 일반.
    인과 표지("때문")는 다른 차원과 거의 겹치지 않아 먼저 본다.
    """
    t = text.lower()
    if any(k in t for k in _CAUSE_KW):
        return GraphDimension.CAUSE
    if any(k in t for k in _SOLUTION_KW):
        return GraphDimension.SOLUTION
    if any(k in t for k in _PROBLEM_KW):
        return GraphDimension.PROBLEM
    return GraphDimension.CLAIM


@dataclass(frozen=True, slots=True)
class GraphNode:
    """논증 그래프의 한 노드 (계층 — parent_id로 부모를 가리킴)."""

    id: str                       # 안정적 식별자 (unit id 또는 합성 id)
    kind: GraphNodeKind
    text: str
    stance: str = "neutral"       # pro | con | neutral
    parent_id: str | None = None  # None이면 루트(주장)
    dimension: GraphDimension = GraphDimension.CLAIM
    depth: int = 0                # 0=주장, 1=차원/근거, 2=증거/반박 …
    weight: int = 1              # 자식 수 등 — 화면이 크기에 활용


@dataclass(frozen=True, slots=True)
class GraphView:
    """한 화제의 논증 그래프 (여러 주장 트리의 숲)."""

    topic_tag_id: uuid.UUID
    nodes: list[GraphNode] = field(default_factory=list)
    claim_count: int = 0
    ground_count: int = 0
    rebuttal_count: int = 0
    evidence_count: int = 0
    summary: str = ""


# ── 평면 unit → 계층 그래프 ─────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class FlatUnit:
    """build_graph_view 입력 — DB ArgumentUnit의 순수-함수용 투영."""

    id: uuid.UUID
    kind: str                     # "claim" | "ground" | "rebuttal" | "question"
    stance: str                   # "pro" | "con" | "neutral"
    text: str
    parent_unit_id: uuid.UUID | None


def _stance_str(s: str) -> str:
    return s if s in ("pro", "con", "neutral") else "neutral"


def build_graph_view(
    topic_tag_id: uuid.UUID,
    units: list[FlatUnit],
    *,
    max_claims: int = 12,
) -> GraphView:
    """평면 ArgumentUnit 리스트를 Kialo식 계층 그래프로 변환 (결정적).

    구조:
      - 각 claim → 루트 노드(depth 0). 차원을 텍스트로 추론해 부착.
      - 같은 차원의 claim들은 화면에서 한 묶음으로 묶이도록 dimension을 부여.
      - ground/rebuttal → parent_unit_id가 가리키는 claim의 자식(depth 1).
        parent가 없으면 같은 차원의 대표 claim에 느슨히 매단다(고아 방지).
      - ground의 ground(증거)는 depth 2 evidence로 승격.
      - question → 루트 옆 열린 질문(부모 없음, depth 0).
    """
    claims = [u for u in units if u.kind == "claim"]
    grounds = [u for u in units if u.kind == "ground"]
    rebuttals = [u for u in units if u.kind == "rebuttal"]
    questions = [u for u in units if u.kind == "question"]

    # 안정 정렬(id 문자열) — 결정성 보장.
    claims = sorted(claims, key=lambda u: str(u.id))[:max_claims]
    claim_ids = {u.id for u in claims}

    nodes: list[GraphNode] = []
    # 1) 루트 주장 노드
    for c in claims:
        dim = classify_dimension(c.text)
        nodes.append(
            GraphNode(
                id=str(c.id),
                kind=GraphNodeKind.CLAIM,
                text=c.text,
                stance=_stance_str(c.stance),
                parent_id=None,
                dimension=dim,
                depth=0,
            )
        )

    # 대표 claim (parent 없는 ground/rebuttal를 느슨히 붙일 곳): 첫 주장.
    fallback_claim_id = str(claims[0].id) if claims else None

    # 2) 근거 / 반박 → 부모 주장의 자식
    child_count: dict[str, int] = {}
    ground_ids: dict[uuid.UUID, str] = {}
    for g in sorted(grounds, key=lambda u: str(u.id)):
        parent = (
            str(g.parent_unit_id)
            if g.parent_unit_id in claim_ids
            else fallback_claim_id
        )
        if parent is None:
            continue
        nid = str(g.id)
        ground_ids[g.id] = nid
        child_count[parent] = child_count.get(parent, 0) + 1
        nodes.append(
            GraphNode(
                id=nid,
                kind=GraphNodeKind.GROUND,
                text=g.text,
                stance=_stance_str(g.stance),
                parent_id=parent,
                depth=1,
            )
        )

    for r in sorted(rebuttals, key=lambda u: str(u.id)):
        # 반박은 claim 또는 ground를 공격할 수 있다.
        if r.parent_unit_id in claim_ids:
            parent = str(r.parent_unit_id)
            depth = 1
        elif r.parent_unit_id in ground_ids:
            parent = ground_ids[r.parent_unit_id]
            depth = 2
        else:
            parent = fallback_claim_id
            depth = 1
        if parent is None:
            continue
        child_count[parent] = child_count.get(parent, 0) + 1
        nodes.append(
            GraphNode(
                id=str(r.id),
                kind=GraphNodeKind.REBUTTAL,
                text=r.text,
                stance="con",
                parent_id=parent,
                depth=depth,
            )
        )

    # 3) 열린 질문 — 부모 없는 depth 0 노드(주장 옆)
    for q in sorted(questions, key=lambda u: str(u.id)):
        nodes.append(
            GraphNode(
                id=str(q.id),
                kind=GraphNodeKind.QUESTION,
                text=q.text,
                stance="neutral",
                parent_id=None,
                depth=0,
            )
        )

    # weight 반영 (자식 수) — 불변 dataclass라 새로 만든다.
    nodes = [
        GraphNode(
            id=n.id, kind=n.kind, text=n.text, stance=n.stance,
            parent_id=n.parent_id, dimension=n.dimension, depth=n.depth,
            weight=1 + child_count.get(n.id, 0),
        )
        for n in nodes
    ]

    summary = _summarize(len(claims), len(grounds), len(rebuttals))
    return GraphView(
        topic_tag_id=topic_tag_id,
        nodes=nodes,
        claim_count=len(claims),
        ground_count=len(grounds),
        rebuttal_count=len(rebuttals),
        evidence_count=0,
        summary=summary,
    )


def _summarize(claims: int, grounds: int, rebuttals: int) -> str:
    if claims == 0:
        return "아직 주장이 없어요. 첫 주장을 더해 논증을 시작해 보세요."
    parts = [f"주장 {claims}개"]
    if grounds:
        parts.append(f"근거 {grounds}개")
    if rebuttals:
        parts.append(f"반박 {rebuttals}개")
    body = ", ".join(parts)
    return (
        f"{body}가 하나의 논증 그래프로 이어져 있어요. "
        "주장을 펼치고, 근거로 떠받치고, 반박으로 시험하면서 함께 다듬어 가요."
    )
