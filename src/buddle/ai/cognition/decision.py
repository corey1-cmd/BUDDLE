"""Stage B — Decision Process (EKB).

Given the Information Processing result (Stage A) and the persona's fixed
dispositions, decide how to respond, following the EKB decision steps:

  1. Problem Recognition — what does the persona need to address? (derived from
     comprehended intent + clarity).
  2. Search — gather internal memory (conversation history) and external
     context (mediator-delivered info). We don't fetch here (pure); we record
     what SHOULD be drawn on, and the prompt builder supplies it.
  3. Alternative Evaluation — score candidate response strategies against
     evaluative criteria, weighted by the persona's dispositions.
  4. Choice — pick the highest-scoring strategy.
  (Select Output / Outcomes / Satisfaction happen at generation time and in the
   next turn; the actual text is produced by the single LLM call.)

Pure and rule-based. The persona's dispositions (not the user's history) shape
evaluation, preserving the bias-safety contract: two personas differ by their
own fixed character, never by profiling the user.
"""

from __future__ import annotations

from buddle.ai.affect.perception import Valence
from buddle.ai.cognition.signals import (
    DecisionResult,
    InformationProcessingResult,
    Intent,
    PersonaDispositions,
    ResponseStrategy,
    SearchResult,
    StrategyCandidate,
)
from buddle.ai.cognition.user_context import UserContextFact

# Base affinity of each intent for each strategy (before persona weighting).
# Rows: intent -> {strategy: base_score in 0..1}.
_INTENT_STRATEGY_BASE: dict[Intent, dict[ResponseStrategy, float]] = {
    Intent.SHARE_NEWS: {
        ResponseStrategy.CELEBRATE: 0.9,
        ResponseStrategy.CONVERSE: 0.4,
        ResponseStrategy.INFORM: 0.1,
    },
    Intent.SEEK_SUPPORT: {
        ResponseStrategy.COMFORT: 0.95,
        ResponseStrategy.CONVERSE: 0.3,
        ResponseStrategy.INFORM: 0.1,
    },
    Intent.ASK_INFO: {
        ResponseStrategy.INFORM: 0.9,
        ResponseStrategy.CLARIFY: 0.3,
        ResponseStrategy.CONVERSE: 0.2,
    },
    Intent.REQUEST_ACTION: {
        ResponseStrategy.ASSIST: 0.9,
        ResponseStrategy.CLARIFY: 0.35,
        ResponseStrategy.INFORM: 0.3,
    },
    Intent.MAKE_CONVERSATION: {
        ResponseStrategy.CONVERSE: 0.8,
        ResponseStrategy.INFORM: 0.2,
        ResponseStrategy.CELEBRATE: 0.2,
    },
    Intent.REFLECT: {
        ResponseStrategy.CONVERSE: 0.6,
        ResponseStrategy.CLARIFY: 0.4,
    },
}


def _recognize_problem(info: InformationProcessingResult) -> str:
    """Step 1: state what must be addressed."""
    mapping = {
        Intent.SHARE_NEWS: "사용자가 좋은 소식을 공유함 — 함께 기뻐할 것",
        Intent.SEEK_SUPPORT: "사용자가 정서적 지지를 필요로 함 — 공감/위로할 것",
        Intent.ASK_INFO: "사용자가 정보를 요청함 — 명확히 답할 것",
        Intent.REQUEST_ACTION: "사용자가 행동을 요청함 — 돕거나 수행할 것",
        Intent.MAKE_CONVERSATION: "사용자가 대화를 이어감 — 따뜻하게 호응할 것",
        Intent.REFLECT: "명확한 요청이 약함 — 경청하고 대화를 열 것",
    }
    base = mapping[info.intent]
    if info.needs_clarification:
        base += " (메시지가 모호 — 명확화 우선 고려)"
    return base


def _has_facts(ctx: UserContextFact | None) -> bool:
    if ctx is None:
        return False
    return bool(ctx.name or ctx.age is not None or ctx.location or ctx.occupation or ctx.explicit_interests)


def _search(
    info: InformationProcessingResult,
    *,
    has_history: bool,
    has_external: bool,
    recalled_memories: tuple[str, ...] = (),
    user_context: UserContextFact | None = None,
) -> SearchResult:
    """Step 2: decide which knowledge sources to draw on.

    Internal search sources (EKB):
      - recalled_memories: LTM entries retrieved for this turn
      - user_context: facts the user explicitly stated about themselves
        (사용자가 직접 고지한 정보 — 이름·나이·위치 등). This is the
        'prior knowledge about this individual' source in EKB's internal search.

    When the caller actually retrieved long-term memories (`recalled_memories`
    non-empty), internal memory IS in use regardless of intent heuristics.
    """
    notes: list[str] = []
    # Internal memory is useful when the message references ongoing topics or
    # asks something that benefits from continuity.
    internal = has_history and info.intent in {
        Intent.ASK_INFO,
        Intent.REQUEST_ACTION,
        Intent.MAKE_CONVERSATION,
        Intent.SEEK_SUPPORT,
    }
    if recalled_memories:
        internal = True
        notes.append(f"장기 기억 {len(recalled_memories)}건 회상(EKB 내부 탐색)")
    elif internal:
        notes.append("대화 이력(내부 기억) 참조")

    # User-disclosed facts: another internal search source.
    # These are FACTS (name, age, location, stated interests), never opinions.
    user_ctx_used = _has_facts(user_context)
    if user_ctx_used:
        fields: list[str] = []
        assert user_context is not None
        if user_context.name:
            fields.append("이름")
        if user_context.age is not None:
            fields.append("나이")
        if user_context.location:
            fields.append("거주지")
        if user_context.occupation:
            fields.append("직업")
        if user_context.explicit_interests:
            fields.append("관심사")
        notes.append(f"사용자 공개 정보 참조({', '.join(fields)})")

    # External context (mediator-delivered bundles) helps informational intents.
    external = has_external and info.intent in {
        Intent.ASK_INFO,
        Intent.REQUEST_ACTION,
    }
    if external:
        notes.append("매개자 전달 정보(외부) 참조")
    if not notes:
        notes.append("현재 메시지만으로 충분")
    return SearchResult(
        internal_memory_used=internal or user_ctx_used,
        external_context_used=external,
        user_context_used=user_ctx_used,
        notes=notes,
        recalled=tuple(recalled_memories[:5]),
    )


def _evaluate(
    info: InformationProcessingResult, disp: PersonaDispositions
) -> list[StrategyCandidate]:
    """Step 3: score candidate strategies, weighted by persona dispositions."""
    base_scores = dict(_INTENT_STRATEGY_BASE.get(info.intent, {}))

    # Clarity gate: if the message is too vague, raise CLARIFY as an option.
    if info.needs_clarification:
        base_scores[ResponseStrategy.CLARIFY] = max(
            base_scores.get(ResponseStrategy.CLARIFY, 0.0), 0.7
        )

    candidates: list[StrategyCandidate] = []
    for strategy, base in base_scores.items():
        score = base
        rationale_bits = [f"기본 적합도 {base:.2f}"]

        # Persona disposition weighting (evaluative criteria).
        if strategy in {ResponseStrategy.CELEBRATE, ResponseStrategy.COMFORT}:
            score *= 0.6 + 0.8 * disp.warmth
            rationale_bits.append(f"온정 가중 x{0.6 + 0.8 * disp.warmth:.2f}")
        if strategy == ResponseStrategy.INFORM:
            score *= 0.6 + 0.8 * disp.informativeness
            rationale_bits.append(f"정보성 가중 x{0.6 + 0.8 * disp.informativeness:.2f}")
        if strategy == ResponseStrategy.CONVERSE:
            score *= 0.6 + 0.8 * disp.proactivity
            rationale_bits.append(f"적극성 가중 x{0.6 + 0.8 * disp.proactivity:.2f}")

        # Affect intensity nudges emotional strategies up.
        if strategy in {ResponseStrategy.CELEBRATE, ResponseStrategy.COMFORT}:
            score += 0.1 * info.affect.intensity

        candidates.append(
            StrategyCandidate(
                strategy=strategy,
                score=round(score, 4),
                rationale="; ".join(rationale_bits),
            )
        )

    candidates.sort(key=lambda c: c.score, reverse=True)
    return candidates


def decide(
    info: InformationProcessingResult,
    *,
    dispositions: PersonaDispositions | None = None,
    has_history: bool = False,
    has_external: bool = False,
    recalled_memories: tuple[str, ...] = (),
    user_context: UserContextFact | None = None,
) -> DecisionResult:
    """Run the full EKB decision process and choose a response strategy.

    `user_context` is passed to the Search step as the internal source for
    user-disclosed facts (EKB: 'prior knowledge about this individual').
    """
    disp = dispositions or PersonaDispositions.default()

    problem = _recognize_problem(info)
    search = _search(
        info,
        has_history=has_history,
        has_external=has_external,
        recalled_memories=recalled_memories,
        user_context=user_context,
    )
    candidates = _evaluate(info, disp)

    # Step 4: Choice — highest score. Deterministic tie-break by enum value.
    if candidates:
        best = max(candidates, key=lambda c: (c.score, c.strategy.value))
        chosen = best.strategy
        chosen_rationale = best.rationale
    else:  # pragma: no cover - base table always non-empty
        chosen = ResponseStrategy.CONVERSE
        chosen_rationale = "기본값"

    # Safety override: a negative-valence message with distress should never be
    # answered with CELEBRATE even if scoring drifted.
    if (
        info.affect.valence == Valence.NEGATIVE
        and info.intent == Intent.SEEK_SUPPORT
        and chosen == ResponseStrategy.CELEBRATE
    ):
        chosen = ResponseStrategy.COMFORT
        chosen_rationale = "안전 오버라이드: 지지 요청에는 위로 우선"

    return DecisionResult(
        problem=problem,
        search=search,
        candidates=candidates,
        chosen=chosen,
        chosen_rationale=chosen_rationale,
    )
