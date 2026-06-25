"""Stage 1/2 stub persona AI.

Looks up the PersonaModel row by model_key and uses its display_name as a
prefix. system_prompt is read but not used (since this is stub echo, not real
inference). Replaced by a real LLM-backed adapter selected by backend_kind
in Stage 2+.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from buddle.ai.interfaces import (
    DialogueTurn,
    PersonaInterpretation,
    PersonaReply,
)
from buddle.db.models.persona_model import PersonaModel


class PersonaStub:
    """Echoes user input, prefixed by the model's display_name. Used when a
    persona's backend_kind is 'stub', and as a unit-test default."""

    def __init__(self, db: AsyncSession | None = None):
        self._db = db

    async def _lookup_display_name(self, model_key: str) -> str:
        if self._db is None:
            return model_key
        result = await self._db.execute(
            select(PersonaModel.display_name).where(PersonaModel.template_key == model_key)
        )
        row = result.first()
        return row[0] if row else model_key

    async def interpret(
        self,
        *,
        persona_name: str,
        model_key: str,
        content_raw: str,
    ) -> PersonaInterpretation:
        display_name = await self._lookup_display_name(model_key)
        transformed = f"[{display_name}] {content_raw}".strip()
        return PersonaInterpretation(
            content_transformed=transformed,
            metadata={
                "stub": "true",
                "persona_name": persona_name,
                "model_key": model_key,
            },
        )

    async def respond_in_dialogue(
        self,
        *,
        persona_name: str,
        model_key: str,
        history: list[DialogueTurn],
        user_message: str,
        recalled_memories: list[str] | None = None,
        conversation_guidance: str = "",
        user_context: object = None,
        knowledge_context: list[str] | None = None,
    ) -> PersonaReply:
        display_name = await self._lookup_display_name(model_key)
        # Tiny "memory" effect: include count of prior user turns
        prior_user_turns = sum(1 for t in history if t.role == "user")
        content = (
            f"[{display_name}] (대화 {prior_user_turns + 1}번째) {user_message} — 잘 들었어요."
        )
        return PersonaReply(
            content=content,
            metadata={"stub": "true", "model_key": model_key},
        )
