"""Admin response schemas."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, EmailStr

from buddle.db.models.enums import AlertStatus, AuthorityStateEnum


class AdminUserRead(BaseModel):
    """관리자 목록 항목 — 슈퍼 관리자 관리 화면용.

    email 은 검증형(EmailStr)이 아니라 str 로 둔다: 이미 저장된 계정을 그대로
    표시할 뿐이고, 시드 계정의 예약 TLD(예: '@buddle.local')를 EmailStr 이
    거부해 목록 전체가 500 나는 것을 막는다.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    is_admin: bool
    is_super_admin: bool
    is_active: bool
    created_at: datetime


class AdminGrantRequest(BaseModel):
    """이메일로 관리자 권한을 부여한다(해당 계정은 이미 가입돼 있어야 함)."""

    email: EmailStr


class SystemStats(BaseModel):
    users_total: int
    users_active: int
    personas_total: int
    personas_active: int
    persona_models_total: int
    persona_models_active: int
    posts_total: int
    posts_public: int
    posts_private: int
    distributions_total: int
    ethics_alerts_open: int
    security_events_open: int


class EthicsAlertRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    target_id: uuid.UUID
    target_type: str
    severity: str
    reason: str | None
    status: AlertStatus
    created_at: datetime
    resolved_at: datetime | None


class SecurityEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    event_type: str
    severity: str
    status: AlertStatus
    detail: dict[str, Any] | None
    created_at: datetime


class AuthorityStateRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    state: AuthorityStateEnum
    changed_at: datetime
    reason: str | None


class AuthorityTokenBalanceRead(BaseModel):
    entity_type: str
    entity_id: uuid.UUID
    balance: float


class AuthoritySnapshot(BaseModel):
    state: AuthorityStateRead
    balances: list[AuthorityTokenBalanceRead]


class MediatorPolicyParams(BaseModel):
    """α/β/γ weights for the mediator's distribution algorithm.

    relevance = α·tag_overlap + β·content_similarity + γ·user_growth_potential
    """

    alpha: float
    beta: float
    gamma: float


class MediatorPolicyUpdate(BaseModel):
    alpha: float | None = None
    beta: float | None = None
    gamma: float | None = None


class IntegrityVerifyResult(BaseModel):
    """Result of verifying the transformation integrity chain."""

    ok: bool
    checked: int
    first_invalid_sequence: int | None
    detail: str


class AuthorityComputeResult(BaseModel):
    """Recomputed authority balances + persisted state."""

    state: str
    central_authority: float
    technician_authority: float
    unverified_count: int
    restoration_count: int
    state_changed: bool


class SystemDigest(BaseModel):
    """Human-readable text digest of current system state."""

    digest: str
    health: str


class AutotuneResult(BaseModel):
    """Outcome of a mediator-policy auto-tuning proposal."""

    changed: bool
    applied: bool
    alpha: float
    beta: float
    gamma: float
    rationale: str
