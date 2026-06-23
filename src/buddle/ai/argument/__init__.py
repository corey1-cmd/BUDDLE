"""Argument mining — pure layer (토론 대시보드의 분석 엔진).

Toulmin-reduced argument extraction (Stab & Gurevych 2017) + deterministic
claim clustering into conversation axes (대화 축). DB access lives in
services/argument_service; the dashboard reads via /v1/topics/{tag}/debate.
"""

from buddle.ai.argument.clustering import (
    Cluster,
    choose_k,
    cluster_claims,
    cosine_distance,
    representative_index,
)
from buddle.ai.argument.extraction import (
    ArgumentKind,
    ArgumentStance,
    ArgumentUnit,
    extract_arguments,
)
from buddle.ai.argument.graph import (
    FlatUnit,
    GraphDimension,
    GraphNode,
    GraphNodeKind,
    GraphView,
    build_graph_view,
    classify_dimension,
)
from buddle.ai.argument.opposition import (
    GeoEdge,
    GeoNode,
    OppositionType,
    OppositionView,
    StanceBucket,
    StanceDistribution,
    build_opposition_view,
    classify_opposition,
)
from buddle.ai.argument.retrieval import (
    ChatContext,
    ChatMode,
    RetrievedUnit,
    build_chat_prompt,
    has_grounding,
)

__all__ = [
    "ArgumentKind",
    "ArgumentStance",
    "ArgumentUnit",
    "ChatContext",
    "ChatMode",
    "Cluster",
    "FlatUnit",
    "GeoEdge",
    "GeoNode",
    "GraphDimension",
    "GraphNode",
    "GraphNodeKind",
    "GraphView",
    "OppositionType",
    "OppositionView",
    "RetrievedUnit",
    "StanceBucket",
    "StanceDistribution",
    "build_chat_prompt",
    "build_graph_view",
    "build_opposition_view",
    "choose_k",
    "classify_dimension",
    "classify_opposition",
    "cluster_claims",
    "cosine_distance",
    "extract_arguments",
    "has_grounding",
    "representative_index",
]
