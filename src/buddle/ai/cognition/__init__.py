"""EKB cognitive pipeline for personas.

Stage A (information processing) + Stage B (decision process) + synthesis into
a compact prompt block. All rule-based and pure; the only model call remains
the persona's single response-generation call.
"""

import dataclasses

from buddle.ai.cognition.caution import CautionReasoningResult, inspect_and_reason
from buddle.ai.cognition.conscience import ConscienceFlag
from buddle.ai.cognition.conscience import inspect as conscience_inspect
from buddle.ai.cognition.debias import inspect as debias_inspect
from buddle.ai.cognition.decision import decide
from buddle.ai.cognition.information import process_information
from buddle.ai.cognition.signals import (
    AttentionResult,
    DecisionResult,
    InformationProcessingResult,
    Intent,
    PersonaDispositions,
    ResponseStrategy,
    SearchResult,
    StrategyCandidate,
)
from buddle.ai.cognition.synthesize import synthesize_prompt_block
from buddle.ai.cognition.user_context import UserContextFact, extract_facts, merge_facts


def run_cognition(
    text: str,
    *,
    dispositions: PersonaDispositions | None = None,
    has_history: bool = False,
    has_external: bool = False,
    topic_offsets: dict[str, float] | None = None,
    recalled_memories: tuple[str, ...] = (),
    conversation_guidance: str = "",
    user_context: UserContextFact | None = None,
) -> tuple[InformationProcessingResult, DecisionResult, str]:
    """Run the full EKB pipeline on a message and return
    (information_result, decision_result, prompt_block).

    Pipeline order (matches the design):
      information processing -> leukocyte conscience gate -> mediator debiasing
      -> decision process (Search uses user_context as internal knowledge source)
      -> synthesis. The conscience gate can OVERRIDE the chosen strategy.

    user_context: accumulated UserContextFact for this session — facts the user
    explicitly stated about themselves. Passed to the Search stage (EKB internal
    search) and rendered in the synthesis block. Never contains opinions.

    topic_offsets (the feedback loop): a small per-topic proactivity offset map.
    If the message's topics intersect it, the persona's proactivity is nudged
    by the matching offset (bounded). Safety/warmth are never touched.
    """
    info = process_information(text)

    # ── 백혈구 AI 유의 단어 게이트 (최우선, 7단계 내부 추론) ────────────
    # conscience보다 먼저 실행. 유의 단어 감지 시 7단계 추론 결과를 caution_guidance로
    # 전달 — 페르소나는 즉시 답변하지 않고 추론 지침을 따라 응답한다.
    # CAUTION_LEXICON_PATH 미설정 시 no-op (has_caution=False).
    caution = inspect_and_reason(text)

    # Leukocyte conscience gate + mediator debiasing (both pure, synchronous).
    conscience = conscience_inspect(text)
    debias = debias_inspect(text)

    disp = dispositions or PersonaDispositions.default()
    if topic_offsets:
        matching = [topic_offsets[t] for t in info.topics if t in topic_offsets]
        if matching:
            offset = max(matching, key=abs)
            disp = disp.with_proactivity_offset(offset)

    # Stage B — Decision Process. user_context enters at the Search step as
    # "internal knowledge about this user" (EKB internal search source).
    decision = decide(
        info,
        dispositions=disp,
        has_history=has_history,
        has_external=has_external,
        recalled_memories=recalled_memories,
        user_context=user_context,
    )

    # Safety override: the conscience gate outranks the decision's choice.
    if conscience.forced_strategy is not None and (decision.chosen != conscience.forced_strategy):
        reason = f"안전 우선 오버라이드({conscience.flag.value})"
        decision = dataclasses.replace(
            decision,
            chosen=conscience.forced_strategy,
            chosen_rationale=reason,
        )

    block = synthesize_prompt_block(
        info,
        decision,
        safety_guidance=conscience.guidance,
        debias_guidance=debias.guidance,
        conversation_guidance=conversation_guidance,
        user_context=user_context,
        caution_guidance=caution.caution_guidance,
    )
    return info, decision, block


__all__ = [
    "AttentionResult",
    "CautionReasoningResult",
    "ConscienceFlag",
    "DecisionResult",
    "InformationProcessingResult",
    "Intent",
    "PersonaDispositions",
    "ResponseStrategy",
    "SearchResult",
    "StrategyCandidate",
    "UserContextFact",
    "conscience_inspect",
    "debias_inspect",
    "decide",
    "extract_facts",
    "inspect_and_reason",
    "merge_facts",
    "process_information",
    "run_cognition",
    "synthesize_prompt_block",
]
