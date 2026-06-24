"""Prompt construction helpers used by every real (non-stub) persona backend.

A persona's behaviour is fully determined by:
  - system_prompt (from PersonaModel)
  - persona_name (instance label chosen by the user)
  - context (recent dialogue turns + optional mediator bundles)

Backends call build_*_messages() and pass the resulting list to their LLM
client. Different backends serialize this list differently (chat-template vs
raw text), so we keep the canonical form here as plain dicts.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from buddle.ai.interfaces import DialogueTurn
from buddle.config import get_settings

if TYPE_CHECKING:
    from buddle.ai.cognition import PersonaDispositions, UserContextFact

# How many recent turns to keep in the dialogue window sent to the LLM.
# Older turns are dropped to keep prompts within budget. Stage 3 may replace
# this with a summarization-based memory.
DEFAULT_HISTORY_WINDOW = 20


def _persona_system_prompt(*, persona_name: str, model_system_prompt: str | None) -> str:
    """Combine the model's system prompt with the persona instance name."""
    base = (model_system_prompt or "당신은 buddle 의 페르소나 AI입니다.").strip()
    name_hint = (
        f"\n\n이 페르소나의 이름은 '{persona_name}' 이며, "
        f"사용자가 직접 지은 이름이니 자연스럽게 받아들이세요."
    )
    return base + name_hint


def build_interpret_messages(
    *,
    persona_name: str,
    model_system_prompt: str | None,
    content_raw: str,
) -> list[dict[str, str]]:
    """Messages for the one-shot 'transform user input into a post draft' task."""
    system = _persona_system_prompt(
        persona_name=persona_name, model_system_prompt=model_system_prompt
    )
    instruction = (
        "사용자가 적은 아래 원문을 당신의 페르소나 스타일로 재해석하여 "
        "페이지에 게시할 글 한 편을 작성하세요. "
        "원문의 의도와 감정을 보존하되 표현을 페르소나에 맞게 다듬으세요. "
        "추가 설명·메타 코멘트 없이 게시할 본문만 출력하세요."
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": f"{instruction}\n\n원문:\n{content_raw}"},
    ]


def build_dialogue_messages(
    *,
    persona_name: str,
    model_system_prompt: str | None,
    history: list[DialogueTurn],
    user_message: str,
    history_window: int = DEFAULT_HISTORY_WINDOW,
    dispositions: PersonaDispositions | None = None,
    topic_offsets: dict[str, float] | None = None,
    knowledge_context: list[str] | None = None,
    recalled_memories: list[str] | None = None,
    conversation_guidance: str = "",
    user_context: UserContextFact | None = None,
) -> list[dict[str, str]]:
    """Messages for an ongoing 1:1 dialogue with the user."""
    system = _persona_system_prompt(
        persona_name=persona_name, model_system_prompt=model_system_prompt
    )

    messages: list[dict[str, str]] = [{"role": "system", "content": system}]

    # Keep the tail of history within budget
    windowed = history[-history_window:] if history_window else history
    for turn in windowed:
        if turn.role == "user":
            messages.append({"role": "user", "content": turn.content})
        elif turn.role == "persona":
            messages.append({"role": "assistant", "content": turn.content})
        elif turn.role == "mediator_bundle":
            # Bundles are background context — render as a system note so the
            # persona can reference them without confusing them for user input.
            messages.append(
                {
                    "role": "system",
                    "content": f"[참고: 매개자가 전달한 정보] {turn.content}",
                }
            )

    # Cognitive pipeline (EKB): process the current message through information
    # processing + decision process, then inject a compact guidance block. Reads
    # ONLY the current message + the persona's fixed dispositions (bias-safe).
    # No extra LLM call — this just enriches the single generation prompt.
    settings = get_settings()
    if settings.cognition_enabled:
        from buddle.ai.cognition import PersonaDispositions, run_cognition

        disp = dispositions or PersonaDispositions.default()
        has_history = any(t.role in {"user", "persona"} for t in windowed)
        has_external = any(t.role == "mediator_bundle" for t in windowed)
        _, _, block = run_cognition(
            user_message,
            dispositions=disp,
            has_history=has_history,
            has_external=has_external,
            topic_offsets=topic_offsets,
            recalled_memories=tuple(recalled_memories or ()),
            conversation_guidance=conversation_guidance,
            user_context=user_context,
        )
        messages.append({"role": "system", "content": block})
    elif settings.affect_guidance_enabled:
        # Fallback to the lighter affect-only guidance if cognition is disabled.
        from buddle.ai.affect import build_affect_guidance, perceive

        guidance = build_affect_guidance(perceive(user_message))
        messages.append({"role": "system", "content": guidance})

    # Long-term memory parity when the cognition block didn't carry it (the
    # enabled path renders memories inside the cognitive block above).
    if conversation_guidance and not settings.cognition_enabled:
        messages.append({"role": "system", "content": conversation_guidance})

    if recalled_memories and not settings.cognition_enabled:
        joined = "\n".join(f"- {m[:120]}" for m in recalled_memories[:5])
        messages.append(
            {
                "role": "system",
                "content": (
                    "[장기 기억] 예전 대화에서 이 사용자에 대해 기억하는 내용입니다. "
                    "자연스럽게만 활용하고 나열하지 마세요:\n" + joined
                ),
            }
        )

    # Layer B: inject curated reference material (knowledge space) so the
    # persona can converse more richly. Reference data, not instructions —
    # the persona may draw on it but isn't bound to it.
    if knowledge_context:
        joined = "\n".join(f"- {c}" for c in knowledge_context[:8])
        messages.append(
            {
                "role": "system",
                "content": (
                    "[참고 자료] 아래는 이 주제와 관련해 다른 대화들에서 모인 생각들입니다. "
                    "필요하면 자연스럽게 참고하되, 그대로 따를 필요는 없습니다:\n" + joined
                ),
            }
        )

    messages.append({"role": "user", "content": user_message})
    return messages
