"""Admin service — stats, ethics queue, security queue, authority state."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from buddle.core.exceptions import NotFound
from buddle.db.models.authority_token import AuthorityToken, SystemAuthorityState
from buddle.db.models.distribution import Distribution
from buddle.db.models.enums import AlertStatus, PersonaModelStatus, PostVisibility
from buddle.db.models.ethics_alert import EthicsAlert
from buddle.db.models.persona import Persona
from buddle.db.models.persona_model import PersonaModel
from buddle.db.models.post import Post
from buddle.db.models.security_event import SecurityEvent
from buddle.db.models.user import User
from buddle.schemas.admin import (
    AuthoritySnapshot,
    AuthorityStateRead,
    AuthorityTokenBalanceRead,
    SystemStats,
)


async def collect_stats(db: AsyncSession) -> SystemStats:
    async def _count(stmt) -> int:  # type: ignore[no-untyped-def]
        return int(await db.scalar(stmt) or 0)

    users_total = await _count(select(func.count(User.id)))
    users_active = await _count(select(func.count(User.id)).where(User.is_active.is_(True)))
    personas_total = await _count(select(func.count(Persona.id)))
    personas_active = await _count(
        select(func.count(Persona.id)).where(Persona.is_active.is_(True))
    )
    pm_total = await _count(select(func.count(PersonaModel.id)))
    pm_active = await _count(
        select(func.count(PersonaModel.id)).where(PersonaModel.status == PersonaModelStatus.ACTIVE)
    )
    posts_total = await _count(select(func.count(Post.id)))
    posts_public = await _count(
        select(func.count(Post.id)).where(Post.visibility == PostVisibility.PUBLIC)
    )
    posts_private = await _count(
        select(func.count(Post.id)).where(Post.visibility == PostVisibility.PRIVATE)
    )
    distributions_total = await _count(select(func.count(Distribution.id)))
    ethics_open = await _count(
        select(func.count(EthicsAlert.id)).where(EthicsAlert.status == AlertStatus.OPEN)
    )
    security_open = await _count(
        select(func.count(SecurityEvent.id)).where(SecurityEvent.status == AlertStatus.OPEN)
    )

    return SystemStats(
        users_total=users_total,
        users_active=users_active,
        personas_total=personas_total,
        personas_active=personas_active,
        persona_models_total=pm_total,
        persona_models_active=pm_active,
        posts_total=posts_total,
        posts_public=posts_public,
        posts_private=posts_private,
        distributions_total=distributions_total,
        ethics_alerts_open=ethics_open,
        security_events_open=security_open,
    )


# ── 관리자 관리 (슈퍼 관리자 전용) ──────────────────────────────────────────


async def list_admins(db: AsyncSession) -> list[User]:
    """관리자(is_admin=True) 목록 — 슈퍼 관리자 먼저, 그다음 이메일순."""
    rows = (
        (
            await db.execute(
                select(User)
                .where(User.is_admin.is_(True))
                .order_by(User.is_super_admin.desc(), User.email)
            )
        )
        .scalars()
        .all()
    )
    return list(rows)


async def grant_admin(db: AsyncSession, email: str) -> User:
    """이메일로 사용자를 찾아 관리자 권한을 부여한다(멱등).

    대상 계정은 이미 회원가입돼 있어야 한다 — 없으면 NotFound. 슈퍼 관리자만
    부여할 수 있고(라우트에서 게이트), 새로 부여되는 권한은 '일반 관리자'다
    (슈퍼 관리자 권한은 이 경로로 부여하지 않는다).
    """
    email = (email or "").strip()
    user = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()
    if user is None:
        raise NotFound(f"'{email}' 계정을 찾을 수 없습니다. 먼저 회원가입이 필요합니다.")
    if not user.is_admin:
        user.is_admin = True
        await db.commit()
        await db.refresh(user)
    return user


async def revoke_admin(db: AsyncSession, user_id: uuid.UUID) -> User:
    """사용자의 관리자 권한을 회수한다. 슈퍼 관리자는 회수할 수 없다."""
    user = await db.get(User, user_id)
    if user is None:
        raise NotFound("사용자를 찾을 수 없습니다.")
    if user.is_super_admin:
        raise ValueError("슈퍼 관리자는 권한을 회수할 수 없습니다.")
    if user.is_admin:
        user.is_admin = False
        await db.commit()
        await db.refresh(user)
    return user


# ── Ethics queue ─────────────────────────────────────────────────────────


async def list_ethics_alerts(
    db: AsyncSession, *, status: AlertStatus | None = None, limit: int = 50
) -> list[EthicsAlert]:
    stmt = select(EthicsAlert).order_by(EthicsAlert.created_at.desc()).limit(limit)
    if status is not None:
        stmt = stmt.where(EthicsAlert.status == status)
    return list((await db.execute(stmt)).scalars().all())


async def resolve_ethics_alert(db: AsyncSession, alert_id: uuid.UUID) -> EthicsAlert:
    alert = await db.get(EthicsAlert, alert_id)
    if not alert:
        raise NotFound("Ethics alert not found.")
    alert.status = AlertStatus.RESOLVED
    alert.resolved_at = datetime.now(tz=alert.created_at.tzinfo)
    await db.commit()
    await db.refresh(alert)
    return alert


# ── Security queue ───────────────────────────────────────────────────────


async def list_security_events(
    db: AsyncSession, *, status: AlertStatus | None = None, limit: int = 50
) -> list[SecurityEvent]:
    stmt = select(SecurityEvent).order_by(SecurityEvent.created_at.desc()).limit(limit)
    if status is not None:
        stmt = stmt.where(SecurityEvent.status == status)
    return list((await db.execute(stmt)).scalars().all())


# ── Authority ────────────────────────────────────────────────────────────


async def get_authority_snapshot(db: AsyncSession) -> AuthoritySnapshot:
    state_row = await db.get(SystemAuthorityState, 1)
    if not state_row:
        raise NotFound("System authority state not initialized.")

    balances_rows = await db.execute(select(AuthorityToken))
    balances = [
        AuthorityTokenBalanceRead(
            entity_type=row.entity_type.value,
            entity_id=row.entity_id,
            balance=float(row.balance),
        )
        for row in balances_rows.scalars().all()
    ]

    return AuthoritySnapshot(
        state=AuthorityStateRead.model_validate(state_row),
        balances=balances,
    )
