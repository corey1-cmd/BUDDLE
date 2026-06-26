"""Admin routes — /v1/admin/*. All endpoints require admin scope."""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from buddle.api.deps import DB, CurrentAdmin, Redis
from buddle.api.v1.admin.analytics import router as analytics_router
from buddle.api.v1.admin.persona_models import router as persona_models_router
from buddle.db.models.enums import AlertStatus
from buddle.schemas.admin import (
    AuthorityComputeResult,
    AuthoritySnapshot,
    AutotuneResult,
    EthicsAlertRead,
    IntegrityVerifyResult,
    MediatorPolicyParams,
    MediatorPolicyUpdate,
    SecurityEventRead,
    SystemDigest,
    SystemStats,
)
from buddle.schemas.plaza import (
    AgentRead,
    AgentRegisterRequest,
    AgentRegisterResponse,
    TickResult,
    VirtualPersonaCreateRequest,
)
from buddle.services import (
    admin_service,
    agent_service,
    central_service,
    feedback_service,
    knowledge_service,
    mediator_policy_service,
    plaza_service,
    technician_service,
)

admin_router = APIRouter(prefix="/admin", tags=["admin"])

# Sub-routers
admin_router.include_router(persona_models_router)
admin_router.include_router(analytics_router)


# ── Stats ─────────────────────────────────────────────────────────


@admin_router.get(
    "/stats",
    response_model=SystemStats,
    summary="System-wide counters",
)
async def get_stats(_: CurrentAdmin, db: DB) -> SystemStats:
    return await admin_service.collect_stats(db)


# ── Ethics queue ──────────────────────────────────────────────────


@admin_router.get(
    "/ethics",
    response_model=list[EthicsAlertRead],
    summary="Ethics alert queue raised by the leukocyte AI",
)
async def list_ethics(
    _: CurrentAdmin,
    db: DB,
    status_filter: AlertStatus | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
) -> list[EthicsAlertRead]:
    alerts = await admin_service.list_ethics_alerts(db, status=status_filter, limit=limit)
    return [EthicsAlertRead.model_validate(a) for a in alerts]


@admin_router.post(
    "/ethics/{alert_id}/resolve",
    response_model=EthicsAlertRead,
    summary="Mark an ethics alert as resolved",
)
async def resolve_ethics(
    alert_id: uuid.UUID,
    _: CurrentAdmin,
    db: DB,
) -> EthicsAlertRead:
    alert = await admin_service.resolve_ethics_alert(db, alert_id)
    return EthicsAlertRead.model_validate(alert)


# ── Security queue ────────────────────────────────────────────────


@admin_router.get(
    "/security",
    response_model=list[SecurityEventRead],
    summary="Security event queue raised by the technician AI",
)
async def list_security(
    _: CurrentAdmin,
    db: DB,
    status_filter: AlertStatus | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
) -> list[SecurityEventRead]:
    events = await admin_service.list_security_events(db, status=status_filter, limit=limit)
    return [SecurityEventRead.model_validate(e) for e in events]


# ── Authority state ───────────────────────────────────────────────


@admin_router.get(
    "/authority",
    response_model=AuthoritySnapshot,
    summary="Current authority state + token balances",
)
async def get_authority(_: CurrentAdmin, db: DB) -> AuthoritySnapshot:
    return await admin_service.get_authority_snapshot(db)


@admin_router.get(
    "/authority/history",
    response_model=list[dict[str, str]],
    summary="Authority state change history (Stage 1: stub empty)",
)
async def get_authority_history(_: CurrentAdmin) -> list[dict[str, str]]:
    # Stage 1: history table not yet introduced. Add in Stage 7+ alongside
    # the technician AI and transformation verification pipeline.
    return []


# ── Technician AI: integrity + dynamic authority ──────────────────


@admin_router.post(
    "/technician/verify-chain",
    response_model=IntegrityVerifyResult,
    summary="Verify the transformation integrity hash chain (tamper-evidence)",
)
async def verify_chain(_: CurrentAdmin, db: DB) -> IntegrityVerifyResult:
    result = await technician_service.verify_integrity_chain(db)
    return IntegrityVerifyResult(
        ok=result.ok,
        checked=result.checked,
        first_invalid_sequence=result.first_invalid_sequence,
        detail=result.detail,
    )


@admin_router.post(
    "/technician/recompute-authority",
    response_model=AuthorityComputeResult,
    summary="Recompute dynamic authority balances and persist NORMAL/TECH_ELEVATED",
)
async def recompute_authority(_: CurrentAdmin, db: DB) -> AuthorityComputeResult:
    comp = await technician_service.recompute_authority(db)
    return AuthorityComputeResult(
        state=comp.snapshot.state.value,
        central_authority=comp.snapshot.central,
        technician_authority=comp.snapshot.technician,
        unverified_count=comp.snapshot.unverified_count,
        restoration_count=comp.snapshot.restoration_count,
        state_changed=comp.state_changed,
    )


@admin_router.post(
    "/technician/transformations/{transformation_id}/verify",
    response_model=AuthorityComputeResult,
    summary="Mark a transformation verified (technician restoration) + recompute",
)
async def verify_transformation(
    transformation_id: uuid.UUID,
    _: CurrentAdmin,
    db: DB,
) -> AuthorityComputeResult:
    comp = await technician_service.verify_transformation(db, transformation_id)
    return AuthorityComputeResult(
        state=comp.snapshot.state.value,
        central_authority=comp.snapshot.central,
        technician_authority=comp.snapshot.technician,
        unverified_count=comp.snapshot.unverified_count,
        restoration_count=comp.snapshot.restoration_count,
        state_changed=comp.state_changed,
    )


# ── Central Manager AI: monitoring / feedback / auto-tuning ────────


@admin_router.get(
    "/monitor/report",
    summary="Full system report (golden signals + engagement + 5-AI status)",
)
async def monitor_report(_: CurrentAdmin, db: DB) -> dict[str, object]:
    report = await central_service.build_report(db)
    return central_service.report_to_payload(report)


@admin_router.get(
    "/monitor/digest",
    response_model=SystemDigest,
    summary="Human-readable text digest of current system state",
)
async def monitor_digest(_: CurrentAdmin, db: DB) -> SystemDigest:
    report = await central_service.build_report(db)
    from buddle.ai.central import render_digest

    return SystemDigest(digest=render_digest(report), health=report.verdict.value)


@admin_router.post(
    "/monitor/snapshot",
    summary="Build a report and persist it as an immutable snapshot",
)
async def monitor_snapshot(_: CurrentAdmin, db: DB) -> dict[str, object]:
    report, snap = await central_service.snapshot_report(db, kind="on_demand")
    payload = central_service.report_to_payload(report)
    payload["snapshot_id"] = str(snap.id)
    return payload


@admin_router.post(
    "/monitor/autotune",
    response_model=AutotuneResult,
    summary="Propose (and optionally apply) a bounded mediator-weight adjustment",
)
async def monitor_autotune(
    _: CurrentAdmin,
    db: DB,
    apply: bool = False,
) -> AutotuneResult:
    proposal = await central_service.autotune_policy(db, apply=apply)
    return AutotuneResult(
        changed=proposal.changed,
        applied=apply and proposal.changed,
        alpha=proposal.alpha,
        beta=proposal.beta,
        gamma=proposal.gamma,
        rationale=proposal.rationale,
    )


# ── Policy ────────────────────────────────────────────────────────


@admin_router.get(
    "/policy/mediator",
    response_model=MediatorPolicyParams,
    summary="Get mediator distribution-algorithm weights",
)
async def get_mediator_policy(_: CurrentAdmin, db: DB) -> MediatorPolicyParams:
    values = await mediator_policy_service.get_policy_values(db)
    return MediatorPolicyParams(alpha=values.alpha, beta=values.beta, gamma=values.gamma)


@admin_router.patch(
    "/policy/mediator",
    response_model=MediatorPolicyParams,
    summary="Update mediator weights (persisted)",
)
async def update_mediator_policy(
    payload: MediatorPolicyUpdate,
    _: CurrentAdmin,
    db: DB,
) -> MediatorPolicyParams:
    row = await mediator_policy_service.update_policy(
        db, alpha=payload.alpha, beta=payload.beta, gamma=payload.gamma
    )
    return MediatorPolicyParams(alpha=row.alpha, beta=row.beta, gamma=row.gamma)


# ── AI agent registry (admin) ──────────────────────────────────────


@admin_router.get(
    "/agents",
    response_model=list[AgentRead],
    summary="List registered AI agents",
)
async def list_agents(_: CurrentAdmin, db: DB) -> Sequence[object]:
    return await agent_service.list_agents(db)


@admin_router.post(
    "/agents",
    response_model=AgentRegisterResponse,
    status_code=201,
    summary="Register an AI agent (returns the API key ONCE)",
)
async def register_agent(
    payload: AgentRegisterRequest,
    _: CurrentAdmin,
    db: DB,
) -> AgentRegisterResponse:
    created = await agent_service.register_agent(
        db,
        name=payload.name,
        kind=payload.kind,
        description=payload.description,
        trust_tier=payload.trust_tier,
    )
    return AgentRegisterResponse(
        agent=AgentRead.model_validate(created.agent), api_key=created.api_key
    )


@admin_router.post(
    "/agents/{agent_id}/deactivate",
    response_model=AgentRead,
    summary="Deactivate an AI agent",
)
async def deactivate_agent(
    agent_id: uuid.UUID,
    _: CurrentAdmin,
    db: DB,
) -> object:
    return await agent_service.set_agent_active(db, agent_id, active=False)


# ── Plaza: virtual personas + scheduler tick (admin) ───────────────


@admin_router.post(
    "/plaza/virtual-personas",
    status_code=201,
    summary="Create a virtual chat persona (system-owned, mediator-driven)",
)
async def create_virtual_persona(
    payload: VirtualPersonaCreateRequest,
    admin: CurrentAdmin,
    db: DB,
) -> dict[str, str]:
    from buddle.db.models.persona import Persona

    # Virtual personas are system-owned; we attach them to the admin user as
    # the nominal owner but mark is_virtual so they're not user-facing.
    persona = Persona(
        user_id=admin.id,
        name=payload.name,
        model_key=payload.model_key,
        is_virtual=True,
        virtual_role=payload.virtual_role.value,
    )
    db.add(persona)
    await db.commit()
    await db.refresh(persona)
    return {"id": str(persona.id), "name": persona.name, "role": payload.virtual_role.value}


@admin_router.post(
    "/plaza/tick",
    response_model=TickResult,
    summary="Run one plaza scheduler cycle (virtual posts + AI comment top-up)",
)
async def plaza_tick(_: CurrentAdmin, db: DB, redis: Redis) -> TickResult:
    result = await plaza_service.tick(db, redis_client=redis)
    return TickResult(posted=result["posted"], commented=result["commented"])


# ── Feedback loop (admin) ──────────────────────────────────────────


@admin_router.post(
    "/feedback/update/{persona_id}",
    summary="Apply one bounded plaza→persona feedback update (topic affinities)",
)
async def update_feedback(
    persona_id: uuid.UUID,
    _: CurrentAdmin,
    db: DB,
) -> dict[str, object]:
    changed = await feedback_service.update_persona_affinities(db, persona_id)
    return {"persona_id": str(persona_id), "changed": changed}


# ── Knowledge space (admin, Layer B) ───────────────────────────────


@admin_router.post("/knowledge/tick", summary="Run one knowledge-space standby sweep")
async def knowledge_tick(_: CurrentAdmin, db: DB) -> dict[str, int]:
    return await knowledge_service.knowledge_tick(db)


@admin_router.get("/knowledge/audit", summary="Recent knowledge-space audit log")
async def knowledge_audit(_: CurrentAdmin, db: DB, limit: int = 50) -> list[dict[str, object]]:
    from sqlalchemy import select

    from buddle.db.models.knowledge_audit import KnowledgeAudit

    rows = (
        await db.execute(
            select(KnowledgeAudit).order_by(KnowledgeAudit.created_at.desc()).limit(min(limit, 200))
        )
    ).scalars()
    return [
        {
            "actor_ai": r.actor_ai,
            "action": r.action,
            "target_type": r.target_type,
            "verdict": r.verdict,
            "note": r.note,
        }
        for r in rows
    ]


@admin_router.post("/knowledge/synthesize/{pool_id}", summary="Manually synthesize a pool")
async def knowledge_synthesize(pool_id: uuid.UUID, _: CurrentAdmin, db: DB) -> dict[str, object]:
    bundle_id = await knowledge_service.synthesize_bundle(db, pool_id)
    return {"pool_id": str(pool_id), "bundle_id": str(bundle_id) if bundle_id else None}


# ── News ingestion (admin) ─────────────────────────────────────────


@admin_router.get("/news/status", summary="News ingest last-run status (Redis)")
async def news_status(_: CurrentAdmin, redis: Redis) -> dict[str, object]:
    from buddle.services.news_service import get_news_status

    return await get_news_status(redis)


@admin_router.get("/news/briefings", summary="Current news briefings cache (latest N)")
async def news_briefings(
    _: CurrentAdmin,
    redis: Redis,
    limit: int = 20,
) -> list[dict[str, object]]:
    from buddle.services.news_service import get_news_briefings

    return await get_news_briefings(redis, limit=limit)


@admin_router.get("/news/digest", summary="Mediator-combined news digest (the combination stage)")
async def news_digest(_: CurrentAdmin, redis: Redis) -> dict[str, object]:
    from buddle.services.news_service import get_news_digest

    return await get_news_digest(redis)


@admin_router.post("/news/tick", summary="Run one news ingest cycle immediately")
async def news_tick_now(_: CurrentAdmin, db: DB, redis: Redis) -> dict[str, object]:
    from buddle.services.news_service import news_tick

    return await news_tick(db, redis=redis)


# ── News sources (where the pipeline searches) ─────────────────────────


class NewsSourceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    kind: str = Field(description="rss | hackernews | devto")
    url: str = Field(default="", max_length=2048)
    limit: int = Field(default=10, ge=1, le=50)
    enabled: bool = True


class NewsSourceToggle(BaseModel):
    enabled: bool


@admin_router.get("/news/sources", summary="List configured news sources")
async def news_sources(_: CurrentAdmin, redis: Redis) -> list[dict[str, object]]:
    from buddle.services.news_service import get_news_sources

    return await get_news_sources(redis)


@admin_router.post("/news/sources", summary="Add a news source (rss/hackernews/devto)")
async def news_source_add(
    body: NewsSourceCreate, _: CurrentAdmin, redis: Redis
) -> dict[str, object]:
    from buddle.services.news_service import add_news_source

    try:
        return await add_news_source(
            redis,
            name=body.name,
            kind=body.kind,
            url=body.url,
            limit=body.limit,
            enabled=body.enabled,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@admin_router.patch("/news/sources/{source_id}", summary="Enable/disable a source")
async def news_source_toggle(
    source_id: str, body: NewsSourceToggle, _: CurrentAdmin, redis: Redis
) -> dict[str, object]:
    from buddle.services.news_service import set_source_enabled

    if not await set_source_enabled(redis, source_id, body.enabled):
        raise HTTPException(status_code=404, detail="source not found")
    return {"id": source_id, "enabled": body.enabled}


@admin_router.delete("/news/sources/{source_id}", summary="Remove a news source")
async def news_source_delete(source_id: str, _: CurrentAdmin, redis: Redis) -> dict[str, object]:
    from buddle.services.news_service import delete_news_source

    if not await delete_news_source(redis, source_id):
        raise HTTPException(status_code=404, detail="source not found")
    return {"id": source_id, "deleted": True}
