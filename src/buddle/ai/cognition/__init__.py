"""EKB cognitive pipeline for personas.

Stage A (information processing) + Stage B (decision process) + synthesis into
a compact prompt block. All rule-based and pure; the only model call remains
the persona's single response-generation call.
"""

import dataclasses

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


def run_cognition(
    text: str,
    *,
    dispositions: PersonaDispositions | None = None,
    has_history: bool = False,
    has_external: bool = False,
    topic_offsets: dict[str, float] | None = None,
    recalled_memories: tuple[str, ...] = (),
    conversation_guidance: str = "",
) -> tuple[InformationProcessingResult, DecisionResult, str]:
    """Run the full EKB pipeline on a message and return
    (information_result, decision_result, prompt_block).

    Pipeline order (matches the design):
      information processing -> leukocyte conscience gate -> mediator debiasing
      -> decision process -> synthesis. The conscience gate can OVERRIDE the
      chosen strategy (e.g. force COMFORT on a self-harm signal); both gates
      contribute guidance to the prompt block. Pure; no LLM call.

    topic_offsets (the feedback loop): a small per-topic proactivity offset map.
    If the message's topics intersect it, the persona's proactivity is nudged
    by the matching offset (bounded) before deciding — fine-tuning emphasis on
    topics the audience responds to. Safety/warmth are never touched.
    """
    info = process_information(text)

    # Leukocyte conscience gate + mediator debiasing (both pure, synchronous).
    conscience = conscience_inspect(text)
    debias = debias_inspect(text)

    disp = dispositions or PersonaDispositions.default()
    # Feedback loop: apply the strongest matching topic offset (bounded). We use
    # the max-magnitude offset among the message's topics so a single update
    # stays small and predictable.
    if topic_offsets:
        matching = [topic_offsets[t] for t in info.topics if t in topic_offsets]
        if matching:
            offset = max(matching, key=abs)
            disp = disp.with_proactivity_offset(offset)

    decision = decide(
        info,
        dispositions=disp,
        has_history=has_history,
        has_external=has_external,
        recalled_memories=recalled_memories,
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
    )
    return info, decision, block


__all__ = [
    "AttentionResult",
    "ConscienceFlag",
    "DecisionResult",
    "InformationProcessingResult",
    "Intent",
    "PersonaDispositions",
    "ResponseStrategy",
    "SearchResult",
    "StrategyCandidate",
    "conscience_inspect",
    "debias_inspect",
    "decide",
    "process_information",
    "run_cognition",
    "synthesize_prompt_block",
]
