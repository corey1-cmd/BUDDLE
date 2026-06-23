"""AI integration interfaces.

Stage 2 expands the PersonaAI protocol with a conversational entry point.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True, slots=True)
class PersonaInterpretation:
    """Result of a persona transforming a user's raw input into a post draft."""

    content_transformed: str
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class DialogueTurn:
    """A single message in a dialogue history (oldest -> newest)."""

    role: str  # 'user' | 'persona' | 'mediator_bundle'
    content: str


@dataclass(frozen=True, slots=True)
class PersonaReply:
    """Persona's response inside an ongoing dialogue."""

    content: str
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class MediatorTagging:
    """Result of the mediator AI tagging + restructuring a persona's output."""

    tag_names: list[str]
    summary: str | None  # mediator's re-form, or None if re-form failed
    content_embedding: list[float] | None = None  # embedding of the (re-formed) content


@dataclass(frozen=True, slots=True)
class DistributionTarget:
    """A persona selected by the mediator as a private-distribution target."""

    target_persona_id: uuid.UUID
    relevance_score: float


class PersonaAI(Protocol):
    """Interface for persona AI implementations.

    Two entry points:
      - interpret(): one-shot transform of user's raw input into a post draft.
      - respond_in_dialogue(): conversational reply, given history.
    """

    async def interpret(
        self,
        *,
        persona_name: str,
        model_key: str,
        content_raw: str,
    ) -> PersonaInterpretation: ...

    async def respond_in_dialogue(
        self,
        *,
        persona_name: str,
        model_key: str,
        history: list[DialogueTurn],
        user_message: str,
        recalled_memories: list[str] | None = None,
        conversation_guidance: str = "",
    ) -> PersonaReply: ...


class MediatorAI(Protocol):
    """Interface for mediator AI implementations."""

    async def tag_and_restructure(
        self,
        *,
        content_transformed: str,
        existing_tags: list[str],
    ) -> MediatorTagging: ...

    async def select_distribution_targets(
        self,
        *,
        source_persona_id: uuid.UUID,
        content_transformed: str,
        tag_names: list[str],
        max_targets: int = 5,
    ) -> list[DistributionTarget]: ...
