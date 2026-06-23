"""Conversation service — the DB orchestration for conversation psychology.

The pure layer (buddle.ai.conversation) computes; this persists and serves:

  recent_window()        — the last N structured turns of a session (the
                           working set / locality of reference) plus the
                           derived mood and salient topics.
  record_turn()          — append one structured turn (with analysis metadata)
                           to conversation_turns.
  load_relationship()    — get-or-create the persona<->user bond.
  update_relationship()  — apply one user turn's affinity delta, recompute the
                           SPT level (with hysteresis), refresh mood + tallies.
  build_user_snapshot()  — cache the central profile as "사용자 대응 성격 특성".

Failure posture: conversation analysis must NEVER break a dialogue — every
caller wraps these defensively, matching the memory/profile layers.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from buddle.ai.affect.perception import Valence
from buddle.ai.conversation import (
    ConversationSituation,
    Mood,
    TurnAffect,
    affinity_delta,
    aggregate_mood,
    apply_delta,
    level_for_score,
)
from buddle.core.logging import get_logger
from buddle.db.models.conversation_turn import ConversationTurn
from buddle.db.models.enums import (
    ConversationSituationEnum,
    MessageRole,
    TurnValenceEnum,
)
from buddle.db.models.relationship import Relationship
from buddle.db.models.user_profile import UserProfile

log = get_logger(__name__)

_WINDOW_DEFAULT = 10  # the ~10-bubble TCB-style working set


@dataclass(frozen=True, slots=True)
class WindowTurn:
    """One turn in the recent window (for prompt context + reuse)."""

    role: str
    content: str
    situation: str | None
    valence: str | None
    intensity: float | None


@dataclass(frozen=True, slots=True)
class RecentWindow:
    """The recent working set: turns + derived mood + salient topics."""

    turns: list[WindowTurn] = field(default_factory=list)
    mood: Mood = field(default_factory=lambda: Mood(0.0, 0.0))
    salient_topics: tuple[str, ...] = ()
    persona_last_was_question: bool = False


def _valence_to_enum(v: Valence) -> TurnValenceEnum:
    return TurnValenceEnum(v.value)


def _enum_to_valence(v: TurnValenceEnum | None) -> Valence | None:
    return Valence(v.value) if v is not None else None


async def recent_window(
    db: AsyncSession, *, session_id: uuid.UUID, n: int = _WINDOW_DEFAULT
) -> RecentWindow:
    """Last `n` structured turns (oldest→newest) + mood + salient topics.

    This is the locality-of-reference working set: mood and topic are measured
    from here, not from the entire history.
    """
    stmt = (
        select(ConversationTurn)
        .where(ConversationTurn.session_id == session_id)
        .order_by(ConversationTurn.created_at.desc())
        .limit(n)
    )
    rows = list((await db.execute(stmt)).scalars().all())
    rows.reverse()  # oldest → newest
    if not rows:
        return RecentWindow()

    turns = [
        WindowTurn(
            role=r.role.value,
            content=r.content,
            situation=r.situation.value if r.situation else None,
            valence=r.valence.value if r.valence else None,
            intensity=r.intensity,
        )
        for r in rows
    ]

    # Mood from the user turns' affect (the energy the persona should match).
    affects = [
        TurnAffect(
            valence=_enum_to_valence(r.valence) or Valence.NEUTRAL, intensity=r.intensity or 0.0
        )
        for r in rows
        if r.role == MessageRole.USER and r.valence is not None
    ]
    mood = aggregate_mood(affects)

    # Salient topics: union over the window's recorded topics, most-recent first.
    seen: set[str] = set()
    topics: list[str] = []
    for r in reversed(rows):  # newest first for recency priority
        for t in r.salient_topics or []:
            if t not in seen:
                seen.add(t)
                topics.append(t)

    persona_last_q = (
        bool(rows)
        and rows[-1].role == MessageRole.PERSONA
        and ("?" in rows[-1].content or "까" in rows[-1].content or "나요" in rows[-1].content)
    )

    return RecentWindow(
        turns=turns,
        mood=mood,
        salient_topics=tuple(topics[:8]),
        persona_last_was_question=persona_last_q,
    )


async def record_turn(
    db: AsyncSession,
    *,
    session_id: uuid.UUID,
    persona_id: uuid.UUID,
    role: MessageRole,
    content: str,
    situation: ConversationSituation | None = None,
    valence: Valence | None = None,
    intensity: float | None = None,
    was_followup: bool = False,
    opened_disclosure: bool = False,
    salient_topics: list[str] | None = None,
    affinity_delta_value: float | None = None,
    commit: bool = True,
) -> None:
    """Append one structured turn with its analysis metadata."""
    db.add(
        ConversationTurn(
            session_id=session_id,
            persona_id=persona_id,
            role=role,
            content=content,
            situation=ConversationSituationEnum(situation.value) if situation else None,
            valence=_valence_to_enum(valence) if valence else None,
            intensity=intensity,
            was_followup=was_followup,
            opened_disclosure=opened_disclosure,
            salient_topics=salient_topics or None,
            affinity_delta=affinity_delta_value,
        )
    )
    if commit:
        await db.commit()


async def find_relationship(
    db: AsyncSession, *, persona_id: uuid.UUID, user_id: uuid.UUID
) -> Relationship | None:
    """Read-only lookup of the bond — never creates a row (for GET endpoints).

    Looking at a relationship shouldn't bring one into existence; that's what
    distinguishes reading from conversing.
    """
    stmt = select(Relationship).where(
        Relationship.persona_id == persona_id, Relationship.user_id == user_id
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def load_relationship(
    db: AsyncSession, *, persona_id: uuid.UUID, user_id: uuid.UUID
) -> Relationship:
    """Get-or-create the persona<->user bond."""
    rel = await find_relationship(db, persona_id=persona_id, user_id=user_id)
    if rel is None:
        rel = Relationship(persona_id=persona_id, user_id=user_id)
        db.add(rel)
        await db.flush()
    return rel


async def update_relationship(
    db: AsyncSession,
    *,
    persona_id: uuid.UUID,
    user_id: uuid.UUID,
    affect: TurnAffect,
    opened_disclosure: bool = False,
    is_reciprocity: bool = False,
    mood: Mood | None = None,
    commit: bool = True,
) -> tuple[Relationship, float, bool]:
    """Apply one user turn to the bond. Returns (relationship, delta, leveled_up).

    Delta uses the Gottman emotional-bank-account formula; the level is
    recomputed with downgrade hysteresis (one rough turn won't demote).
    """
    rel = await load_relationship(db, persona_id=persona_id, user_id=user_id)
    prev_level = int(rel.level)

    delta = affinity_delta(
        affect,
        opened_disclosure=opened_disclosure,
        is_reciprocity=is_reciprocity,
        current_level=prev_level,
    )
    rel.affinity_score = apply_delta(float(rel.affinity_score), delta)
    new_level = int(level_for_score(float(rel.affinity_score), current_level=prev_level))
    rel.level = new_level

    if affect.valence == Valence.POSITIVE:
        rel.positive_turns = int(rel.positive_turns) + 1
    elif affect.valence == Valence.NEGATIVE:
        rel.negative_turns = int(rel.negative_turns) + 1
    rel.turn_count = int(rel.turn_count) + 1

    if mood is not None:
        rel.mood_valence = mood.valence
        rel.mood_energy = mood.energy

    if commit:
        await db.commit()
    return rel, delta, new_level > prev_level


async def build_user_snapshot(
    db: AsyncSession, *, user_id: uuid.UUID
) -> dict[str, float | bool] | None:
    """Cache the central profile as the persona's "사용자 대응 성격 특성".

    Connection-only: OCEAN + confidence + opt-out flag. Returns None when the
    user has no profile or has opted out (the persona then stays neutral).
    """
    stmt = select(UserProfile).where(UserProfile.user_id == user_id)
    profile = (await db.execute(stmt)).scalar_one_or_none()
    if profile is None or profile.profile_opt_out:
        return None
    return {
        "o": round(float(profile.o), 3),
        "c": round(float(profile.c), 3),
        "e": round(float(profile.e), 3),
        "a": round(float(profile.a), 3),
        "n": round(float(profile.n), 3),
        "confidence": round(float(profile.confidence), 3),
    }
