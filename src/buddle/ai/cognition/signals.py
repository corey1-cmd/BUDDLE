"""Shared data structures for the EKB cognitive pipeline.

The pipeline models how a persona processes an incoming message the way the
Engel-Kollat-Blackwell consumer model describes cognition: an Information
Processing stage (exposure -> attention -> comprehension -> acceptance ->
retention) followed by a Decision Process (problem recognition -> search ->
alternative evaluation -> choice -> output). These dataclasses are the typed
hand-offs between stages.

All stage cores are pure (no I/O, no LLM). The only model call in the whole
system stays the single response-generation call the persona already makes;
the cognitive stages just enrich (and compress) the prompt for it. This keeps
added cost at zero LLM calls while giving the persona staged, inspectable
understanding.

Bias-safety contract (same as ai/affect): every stage here reads only the
CURRENT message (plus the persona's own fixed attributes). No user profiling,
no learning from history, no style mimicry.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from buddle.ai.affect.perception import PerceivedAffect


class Intent(StrEnum):
    """The communicative intent comprehended from the message."""

    SHARE_NEWS = "share_news"  # sharing something that happened (often good)
    SEEK_SUPPORT = "seek_support"  # venting / seeking emotional support
    ASK_INFO = "ask_info"  # asking a question / seeking information
    REQUEST_ACTION = "request_action"  # asking the persona to do something
    MAKE_CONVERSATION = "make_conversation"  # casual / social continuation
    REFLECT = "reflect"  # neutral statement, no clear ask


@dataclass(frozen=True, slots=True)
class AttentionResult:
    """Stage 2 (Attention): the selective filter — what stood out."""

    salient_tokens: list[str]
    is_question: bool
    is_request: bool
    is_urgent: bool


@dataclass(frozen=True, slots=True)
class InformationProcessingResult:
    """Output of Stage A (Information Processing), transferred to MEMORY and
    consumed by the Decision Process.

    Fields map to the EKB information-processing sub-stages:
      - language/raw_len: Exposure (stimulus received)
      - attention: Attention (selective filter)
      - intent/affect/topics: Comprehension (meaning interpretation)
      - clarity/needs_clarification: Acceptance (relevance/credibility judged)
      - retained_summary/salient_points: Retention (transfer to long-term memory)
    """

    language: str  # 'ko' | 'en' | 'mixed' | 'unknown'
    raw_len: int
    attention: AttentionResult
    intent: Intent
    affect: PerceivedAffect
    topics: list[str]
    clarity: float  # 0..1 how clear/specific the message is
    needs_clarification: bool
    retained_summary: str
    salient_points: list[str] = field(default_factory=list)


# ── Stage B: Decision Process ────────────────────────────────────────────


class ResponseStrategy(StrEnum):
    """The chosen response approach (Decision Process 'Choice')."""

    CELEBRATE = "celebrate"  # amplify good news (ACR)
    COMFORT = "comfort"  # validate + support distress
    INFORM = "inform"  # answer the question / give information
    ASSIST = "assist"  # carry out / help with a requested action
    CLARIFY = "clarify"  # ask a clarifying question (low message clarity)
    CONVERSE = "converse"  # warm, open-ended social continuation


@dataclass(frozen=True, slots=True)
class PersonaDispositions:
    """The persona's FIXED decision variables + external factors (EKB).

    These are attributes of the PERSONA, set at creation — NOT learned from the
    user (that would violate the bias-safety contract). Different personas with
    different dispositions respond differently to the same input, which is what
    gives them distinct, consistent character.

    Modeled as a few interpretable knobs distilled from the diagram's decision
    variables (beliefs/motives/attitudes/lifestyle/intentions/evaluative
    criteria/normative compliance) and external factors (cultural norms/social
    class/reference group/family/unexpected circumstances). We don't need all
    twelve as separate fields; these capture the behaviorally-relevant axes.
    """

    warmth: float = 0.7  # attitude/motive: how emotionally warm (0..1)
    informativeness: float = 0.6  # evaluative criterion: prefers giving info
    proactivity: float = 0.5  # intention: how much to drive the conversation
    formality: float = 0.4  # cultural/normative: tone formality (0 casual..1 formal)
    # Free-form persona context (interests etc.) for prompt color, not scoring.
    interest_tags: list[str] = field(default_factory=list)

    @staticmethod
    def default() -> PersonaDispositions:
        return PersonaDispositions()

    def with_proactivity_offset(self, offset: float) -> PersonaDispositions:
        """Return a copy with proactivity nudged by `offset`, clamped to [0,1].

        Used by the feedback loop to fine-tune emphasis on a topic. Only
        proactivity moves; warmth/informativeness/formality (and safety, which
        lives elsewhere) are untouched, so feedback can't distort character.
        """
        import dataclasses

        new_p = max(0.0, min(1.0, self.proactivity + offset))
        return dataclasses.replace(self, proactivity=new_p)


@dataclass(frozen=True, slots=True)
class StrategyCandidate:
    strategy: ResponseStrategy
    score: float
    rationale: str


@dataclass(frozen=True, slots=True)
class SearchResult:
    """Decision Process 'Search': internal memory + external context pulled in.

    `recalled` carries actual long-term-memory contents retrieved for this
    turn (EKB internal search made literal); empty when nothing was recalled
    or the memory layer is disabled.

    `user_context_used` is set when the accumulated UserContextFact (facts the
    user explicitly stated about themselves) was consulted — another form of
    internal search alongside LTM recall.
    """

    internal_memory_used: bool
    external_context_used: bool
    user_context_used: bool = False
    notes: list[str] = field(default_factory=list)
    recalled: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class DecisionResult:
    """Output of Stage B (Decision Process): the chosen response strategy plus
    the reasoning trail (problem recognition -> search -> evaluation -> choice)."""

    problem: str  # what the persona recognizes it must address
    search: SearchResult
    candidates: list[StrategyCandidate]
    chosen: ResponseStrategy
    chosen_rationale: str
