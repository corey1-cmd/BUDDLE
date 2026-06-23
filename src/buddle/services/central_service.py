"""Central manager service — gather metrics, build the SystemReport, persist
snapshots, and (optionally) apply bounded policy auto-tuning.

What the central manager can and cannot do (clean AI-to-AI boundaries):
  - READS everything: users, sessions, posts, tags, ethics alerts, the
    technician's authority state and integrity verdict.
  - WRITES only: metric snapshots (append-only) and — within hard guardrails —
    the mediator policy weights. It NEVER writes the transformation chain or
    flips authority state; those belong to the technician. This keeps the
    privilege separation the spec requires: the monitor cannot forge the
    security record it monitors.

Engagement metrics are computed from real data (users, user_sessions, tags).
Latency/error golden signals are owned by Prometheus at the edge; here they
are reported as 0 with a note, to avoid fabricating numbers the DB can't know.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from buddle.ai.central import (
    AIComponentStatus,
    EngagementMetrics,
    GoldenSignals,
    HealthThresholds,
    SystemReport,
    TopicCount,
    compute_verdict,
    propose_weights,
    render_digest,
)
from buddle.ai.central.autotune import WeightProposal
from buddle.config import get_settings
from buddle.core.logging import get_logger
from buddle.db.models.enums import PersonaBackendKind
from buddle.db.models.ethics_alert import EthicsAlert
from buddle.db.models.metric_snapshot import MetricSnapshot
from buddle.db.models.persona_model import PersonaModel
from buddle.db.models.post import Post
from buddle.db.models.session import UserSession
from buddle.db.models.tag import PostTag, Tag
from buddle.db.models.user import User
from buddle.services import session_service, technician_service
from buddle.services.mediator_policy_service import get_policy_values, update_policy

log = get_logger(__name__)


async def _count_active_users(db: AsyncSession, since: datetime) -> int:
    return int(
        await db.scalar(
            select(func.count(distinct(UserSession.user_id))).where(
                UserSession.last_seen_at >= since
            )
        )
        or 0
    )


async def _engagement(db: AsyncSession, window_days: int) -> EngagementMetrics:
    now = datetime.now(UTC)
    dau = await _count_active_users(db, now - timedelta(days=1))
    wau = await _count_active_users(db, now - timedelta(days=7))
    mau = await _count_active_users(db, now - timedelta(days=30))
    stickiness = (dau / mau) if mau > 0 else 0.0

    window_start = now - timedelta(days=window_days)

    new_users = int(
        await db.scalar(select(func.count(User.id)).where(User.created_at >= window_start)) or 0
    )
    total_users = int(await db.scalar(select(func.count(User.id))) or 0)
    users_before = max(total_users - new_users, 0)
    # Growth rate proxy: new users over the base at window start. Churn is not
    # tracked yet (no deactivation signal), so this is new-user growth only.
    growth_rate = (new_users / users_before) if users_before > 0 else 0.0

    # Session duration over closed sessions in the window.
    closed = list(
        (
            await db.execute(
                select(UserSession).where(
                    UserSession.ended_at.isnot(None),
                    UserSession.started_at >= window_start,
                )
            )
        ).scalars()
    )
    total_sessions = len(closed)
    if total_sessions:
        durations_min = []
        activities = []
        for s in closed:
            start = s.started_at
            end = s.ended_at or s.last_seen_at
            if start.tzinfo is None:
                start = start.replace(tzinfo=UTC)
            if end.tzinfo is None:
                end = end.replace(tzinfo=UTC)
            durations_min.append(max((end - start).total_seconds() / 60.0, 0.0))
            activities.append(s.activity_count)
        avg_session_minutes = sum(durations_min) / total_sessions
        avg_activities = sum(activities) / total_sessions
    else:
        avg_session_minutes = 0.0
        avg_activities = 0.0

    return EngagementMetrics(
        dau=dau,
        wau=wau,
        mau=mau,
        stickiness=stickiness,
        new_users_in_window=new_users,
        growth_rate=growth_rate,
        avg_session_minutes=round(avg_session_minutes, 2),
        avg_activities_per_session=round(avg_activities, 2),
        total_sessions_in_window=total_sessions,
    )


async def _top_topics(db: AsyncSession, window_days: int, limit: int = 8) -> list[TopicCount]:
    window_start = datetime.now(UTC) - timedelta(days=window_days)
    rows = (
        await db.execute(
            select(Tag.name, func.count(PostTag.post_id).label("c"))
            .join(PostTag, PostTag.tag_id == Tag.id)
            .join(Post, Post.id == PostTag.post_id)
            .where(Post.created_at >= window_start)
            .group_by(Tag.name)
            .order_by(func.count(PostTag.post_id).desc())
            .limit(limit)
        )
    ).all()
    return [TopicCount(tag=r[0], count=int(r[1])) for r in rows]


async def _traffic(db: AsyncSession, window_days: int) -> GoldenSignals:
    """DB-derived traffic proxy (posts created in window). Latency/error/
    saturation are owned by Prometheus at the edge and reported as 0 here."""
    window_start = datetime.now(UTC) - timedelta(days=window_days)
    posts = int(
        await db.scalar(select(func.count(Post.id)).where(Post.created_at >= window_start)) or 0
    )
    minutes = max(window_days * 24 * 60, 1)
    return GoldenSignals(
        traffic_requests=posts,
        requests_per_min=round(posts / minutes, 4),
        error_rate=0.0,
        latency_p50_ms=0.0,
        latency_p95_ms=0.0,
        saturation_pct=0.0,
    )


async def _components(
    db: AsyncSession, *, authority_state: str, integrity_ok: bool, open_alerts: int
) -> list[AIComponentStatus]:
    # Persona: how many models are active across which backends.
    active_models = int(
        await db.scalar(
            select(func.count(PersonaModel.template_key)).where(PersonaModel.status == "active")
        )
        or 0
    )
    backends = list(
        (
            await db.execute(
                select(distinct(PersonaModel.backend_kind)).where(PersonaModel.status == "active")
            )
        ).scalars()
    )
    backend_names = (
        ", ".join(b.value if isinstance(b, PersonaBackendKind) else str(b) for b in backends)
        or "none"
    )

    return [
        AIComponentStatus(
            name="페르소나",
            state="ok" if active_models > 0 else "degraded",
            detail=f"active 모델 {active_models}개 (backends: {backend_names})",
        ),
        AIComponentStatus(name="매개자", state="ok", detail="임베딩 기반 분배 가동"),
        AIComponentStatus(
            name="백혈구",
            state="warn" if open_alerts > 0 else "ok",
            detail=f"미처리 윤리 알림 {open_alerts}건",
        ),
        AIComponentStatus(
            name="기술자",
            state="elevated" if authority_state == "tech_elevated" else "ok",
            detail=("무결성 정상" if integrity_ok else "무결성 검증 실패 ⚠"),
        ),
        AIComponentStatus(name="중앙관리자", state="ok", detail="모니터링 가동"),
    ]


def _thresholds() -> HealthThresholds:
    s = get_settings()
    return HealthThresholds(
        error_rate_warn=s.slo_error_rate_warn,
        error_rate_critical=s.slo_error_rate_critical,
        latency_p95_warn_ms=s.slo_latency_p95_warn_ms,
        latency_p95_critical_ms=s.slo_latency_p95_critical_ms,
        open_alerts_warn=s.health_open_alerts_warn,
        open_alerts_critical=s.health_open_alerts_critical,
    )


async def build_report(db: AsyncSession) -> SystemReport:
    """Gather all signals and assemble the SystemReport (with verdict)."""
    settings = get_settings()
    window_days = settings.engagement_window_days

    # Close idle sessions first so duration stats are accurate.
    await session_service.close_stale_sessions(db)

    open_alerts = int(
        await db.scalar(select(func.count(EthicsAlert.id)).where(EthicsAlert.status == "open")) or 0
    )

    integrity = await technician_service.verify_integrity_chain(db)
    auth = await technician_service.recompute_authority(db)
    authority_state = auth.snapshot.state.value

    golden = await _traffic(db, window_days)
    engagement = await _engagement(db, window_days)
    topics = await _top_topics(db, window_days)
    components = await _components(
        db,
        authority_state=authority_state,
        integrity_ok=integrity.ok,
        open_alerts=open_alerts,
    )

    verdict, notes = compute_verdict(
        golden=golden,
        open_alerts=open_alerts,
        authority_state=authority_state,
        integrity_ok=integrity.ok,
        thresholds=_thresholds(),
    )
    notes.append("지연/에러율 골든시그널은 엣지(Prometheus) 소스이며 본 리포트에는 0으로 표기됨.")

    return SystemReport(
        generated_at=datetime.now(UTC).isoformat(),
        window_days=window_days,
        verdict=verdict,
        golden=golden,
        engagement=engagement,
        components=components,
        top_topics=topics,
        open_ethics_alerts=open_alerts,
        authority_state=authority_state,
        integrity_ok=integrity.ok,
        notes=notes,
    )


def report_to_payload(r: SystemReport) -> dict:  # type: ignore[type-arg]
    """Public wrapper for serializing a SystemReport (used by routes)."""
    return _report_to_payload(r)


def _report_to_payload(r: SystemReport) -> dict:  # type: ignore[type-arg]
    """Serialize a SystemReport to a JSON-able dict for snapshot storage."""
    return {
        "generated_at": r.generated_at,
        "window_days": r.window_days,
        "verdict": r.verdict.value,
        "golden": {
            "traffic_requests": r.golden.traffic_requests,
            "requests_per_min": r.golden.requests_per_min,
            "error_rate": r.golden.error_rate,
            "latency_p50_ms": r.golden.latency_p50_ms,
            "latency_p95_ms": r.golden.latency_p95_ms,
            "saturation_pct": r.golden.saturation_pct,
        },
        "engagement": {
            "dau": r.engagement.dau,
            "wau": r.engagement.wau,
            "mau": r.engagement.mau,
            "stickiness": r.engagement.stickiness,
            "new_users_in_window": r.engagement.new_users_in_window,
            "growth_rate": r.engagement.growth_rate,
            "avg_session_minutes": r.engagement.avg_session_minutes,
            "avg_activities_per_session": r.engagement.avg_activities_per_session,
            "total_sessions_in_window": r.engagement.total_sessions_in_window,
        },
        "components": [
            {"name": c.name, "state": c.state, "detail": c.detail} for c in r.components
        ],
        "top_topics": [{"tag": t.tag, "count": t.count} for t in r.top_topics],
        "open_ethics_alerts": r.open_ethics_alerts,
        "authority_state": r.authority_state,
        "integrity_ok": r.integrity_ok,
        "notes": r.notes,
    }


async def snapshot_report(
    db: AsyncSession, *, kind: str = "on_demand"
) -> tuple[SystemReport, MetricSnapshot]:
    """Build a report and persist it as an immutable snapshot."""
    report = await build_report(db)
    snap = MetricSnapshot(
        kind=kind,
        payload=_report_to_payload(report),
        health=report.verdict.value,
    )
    db.add(snap)
    await db.commit()
    await db.refresh(snap)
    log.info("central.snapshot", health=report.verdict.value, kind=kind)
    return report, snap


async def get_digest(db: AsyncSession) -> str:
    """Human-readable text digest of the current system state."""
    report = await build_report(db)
    return render_digest(report)


async def autotune_policy(db: AsyncSession, *, apply: bool) -> WeightProposal:
    """Propose (and optionally apply) a bounded mediator-weight adjustment.

    Auto-tuning is skipped when the system is unhealthy (the proposal returns
    changed=False with a rationale). Applying writes the mediator policy via
    the policy service — the only mutation the central manager performs beyond
    snapshots.
    """
    report = await build_report(db)
    current = await get_policy_values(db)
    healthy = report.verdict.value == "ok"

    proposal = propose_weights(
        current_alpha=current.alpha,
        current_beta=current.beta,
        current_gamma=current.gamma,
        stickiness=report.engagement.stickiness,
        avg_session_minutes=report.engagement.avg_session_minutes,
        healthy=healthy,
    )

    if apply and proposal.changed:
        await update_policy(db, alpha=proposal.alpha, beta=proposal.beta, gamma=proposal.gamma)
        log.info(
            "central.autotune_applied",
            alpha=proposal.alpha,
            beta=proposal.beta,
            gamma=proposal.gamma,
        )

    return proposal
