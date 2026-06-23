"""AI agent registry service — register agents, authenticate by API key.

The plaintext API key is returned ONCE on registration and never stored; we
keep only its argon2 hash. Authentication hashes the presented key and
compares. Trust tier governs rate limits / auto-approval downstream.
"""

from __future__ import annotations

import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from buddle.core.exceptions import Conflict, NotFound, Unauthorized
from buddle.db.models.ai_agent import AIAgent
from buddle.db.models.enums import AgentKind
from buddle.security.password import hash_password, verify_password

# API keys are prefixed so they're recognizable and greppable in logs as
# "an agent key was leaked" without revealing the secret.
_KEY_PREFIX = "bdl_agent_"


@dataclass(frozen=True, slots=True)
class AgentCreated:
    agent: AIAgent
    api_key: str  # shown once; not stored


def _generate_api_key() -> str:
    return _KEY_PREFIX + secrets.token_urlsafe(32)


async def register_agent(
    db: AsyncSession,
    *,
    name: str,
    kind: AgentKind,
    description: str | None = None,
    trust_tier: int = 0,
) -> AgentCreated:
    """Register a new agent. Returns the agent + its one-time API key."""
    api_key = _generate_api_key()
    agent = AIAgent(
        name=name,
        kind=kind,
        description=description,
        api_key_hash=hash_password(api_key),
        trust_tier=max(0, min(trust_tier, 3)),
        is_active=True,
    )
    db.add(agent)
    try:
        await db.commit()
    except IntegrityError as e:
        await db.rollback()
        raise Conflict("An agent with this name already exists.", detail={"name": name}) from e
    await db.refresh(agent)
    return AgentCreated(agent=agent, api_key=api_key)


async def authenticate_agent(db: AsyncSession, api_key: str) -> AIAgent:
    """Resolve and verify an agent by its API key.

    We can't index by a hashed key, so we scan active agents and verify the key
    against each hash. Agent counts are small (operators register a handful), so
    this is fine; if it ever grows, add a fast key-id prefix lookup.
    """
    if not api_key or not api_key.startswith(_KEY_PREFIX):
        raise Unauthorized("Invalid agent API key.")

    agents = list((await db.execute(select(AIAgent).where(AIAgent.is_active.is_(True)))).scalars())
    for agent in agents:
        if verify_password(api_key, agent.api_key_hash):
            agent.last_seen_at = datetime.now(UTC)
            await db.commit()
            return agent
    raise Unauthorized("Invalid agent API key.")


async def get_agent(db: AsyncSession, agent_id: uuid.UUID) -> AIAgent:
    agent = await db.get(AIAgent, agent_id)
    if agent is None:
        raise NotFound("Agent not found.")
    return agent


async def list_agents(db: AsyncSession) -> list[AIAgent]:
    return list((await db.execute(select(AIAgent).order_by(AIAgent.name))).scalars())


async def set_agent_active(db: AsyncSession, agent_id: uuid.UUID, *, active: bool) -> AIAgent:
    agent = await get_agent(db, agent_id)
    agent.is_active = active
    await db.commit()
    await db.refresh(agent)
    return agent
