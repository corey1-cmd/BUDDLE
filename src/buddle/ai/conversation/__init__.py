"""Human conversation psychology — pure layer.

Makes persona dialogue feel like real human conversation, grounded in:
  * Social Penetration Theory (Altman & Taylor 1973) — relationship levels,
    breadth/depth, "Current Level + 1" (relationship.py).
  * Gottman emotional bank account + 5:1 ratio / negativity bias — the
    running affinity score (relationship.py).
  * Reference locality — the recent ~10-bubble window is the working set for
    mood and topic (situation.py + services/conversation_service).
  * Ten conversation principles applied conditionally, fused with EKB
    (principles.py).
"""

from buddle.ai.conversation.principles import (
    ConversationContext,
    build_conversation_guidance,
)
from buddle.ai.conversation.relationship import (
    RelationshipLevel,
    TurnAffect,
    affinity_delta,
    apply_delta,
    disclosure_target_level,
    level_for_score,
)
from buddle.ai.conversation.situation import (
    ConversationSituation,
    Mood,
    aggregate_mood,
    detect_decline_needed,
    detect_distress,
    detect_winding_down,
    is_request,
    situation_for,
)

__all__ = [
    "ConversationContext",
    "ConversationSituation",
    "Mood",
    "RelationshipLevel",
    "TurnAffect",
    "affinity_delta",
    "aggregate_mood",
    "apply_delta",
    "build_conversation_guidance",
    "detect_decline_needed",
    "detect_distress",
    "detect_winding_down",
    "disclosure_target_level",
    "is_request",
    "level_for_score",
    "situation_for",
]
