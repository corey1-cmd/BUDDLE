"""Central manager report structures + pure verdict/formatting logic.

The central manager's job (per the spec's evaluation criteria) is to observe
the whole system in detail, summarize it *readably*, and surface a clear
health verdict for the human admin. This module defines the report shape and
the PURE logic that turns raw counts into a verdict and a human-readable
digest. The service layer gathers the raw numbers; everything here is testable
without a DB.

Monitoring model = SRE golden signals (traffic, errors, latency, saturation)
+ product engagement (DAU/MAU stickiness, avg session length, growth rate,
top conversation topics) + the 5-AI ecosystem status (incl. the technician's
authority state).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class HealthVerdict(StrEnum):
    OK = "ok"
    WARN = "warn"
    CRITICAL = "critical"


_VERDICT_RANK = {HealthVerdict.OK: 0, HealthVerdict.WARN: 1, HealthVerdict.CRITICAL: 2}


def worst(*verdicts: HealthVerdict) -> HealthVerdict:
    return max(verdicts, key=lambda v: _VERDICT_RANK[v])


@dataclass(frozen=True, slots=True)
class GoldenSignals:
    """SRE four golden signals over the reporting window."""

    traffic_requests: int  # total requests in window
    requests_per_min: float
    error_rate: float  # failed / total in [0, 1]
    latency_p50_ms: float
    latency_p95_ms: float
    saturation_pct: float  # 0..100 (e.g. inflight/connection-pool usage proxy)


@dataclass(frozen=True, slots=True)
class EngagementMetrics:
    """Product engagement for the human-facing dashboard."""

    dau: int
    wau: int
    mau: int
    stickiness: float  # DAU/MAU in [0, 1]
    new_users_in_window: int
    growth_rate: float  # (new - churned)/start, can be negative
    avg_session_minutes: float  # average continuous usage time
    avg_activities_per_session: float
    total_sessions_in_window: int


@dataclass(frozen=True, slots=True)
class TopicCount:
    tag: str
    count: int


@dataclass(frozen=True, slots=True)
class AIComponentStatus:
    """Status line for one of the five AIs."""

    name: str
    state: str  # 'ok' | 'degraded' | 'elevated' | ...
    detail: str


@dataclass(frozen=True, slots=True)
class SystemReport:
    generated_at: str  # ISO-8601
    window_days: int
    verdict: HealthVerdict
    golden: GoldenSignals
    engagement: EngagementMetrics
    components: list[AIComponentStatus]
    top_topics: list[TopicCount]
    open_ethics_alerts: int
    authority_state: str  # normal | tech_elevated
    integrity_ok: bool
    notes: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class HealthThresholds:
    error_rate_warn: float
    error_rate_critical: float
    latency_p95_warn_ms: float
    latency_p95_critical_ms: float
    open_alerts_warn: int
    open_alerts_critical: int


def compute_verdict(
    *,
    golden: GoldenSignals,
    open_alerts: int,
    authority_state: str,
    integrity_ok: bool,
    thresholds: HealthThresholds,
) -> tuple[HealthVerdict, list[str]]:
    """Derive an overall health verdict + human-readable reasons.

    Security-relevant conditions dominate: a failed integrity chain or a
    TECH_ELEVATED authority state is always CRITICAL — those mean the system
    may be compromised, which outranks performance signals.
    """
    verdict = HealthVerdict.OK
    notes: list[str] = []

    # Security conditions first (fail loud).
    if not integrity_ok:
        verdict = worst(verdict, HealthVerdict.CRITICAL)
        notes.append("무결성 체인 검증 실패 — 변형 로그 변조 가능성. 즉시 점검 필요.")
    if authority_state == "tech_elevated":
        verdict = worst(verdict, HealthVerdict.CRITICAL)
        notes.append(
            "권한 상태 TECH_ELEVATED — 중앙관리자 비정당 변형 누적으로 기술자 자동 권한 상승."
        )

    # Error rate
    if golden.error_rate >= thresholds.error_rate_critical:
        verdict = worst(verdict, HealthVerdict.CRITICAL)
        notes.append(f"에러율 {golden.error_rate:.1%} (임계 {thresholds.error_rate_critical:.0%})")
    elif golden.error_rate >= thresholds.error_rate_warn:
        verdict = worst(verdict, HealthVerdict.WARN)
        notes.append(f"에러율 다소 높음 {golden.error_rate:.1%}")

    # Latency p95
    if golden.latency_p95_ms >= thresholds.latency_p95_critical_ms:
        verdict = worst(verdict, HealthVerdict.CRITICAL)
        notes.append(
            f"p95 지연 {golden.latency_p95_ms:.0f}ms (임계 {thresholds.latency_p95_critical_ms:.0f}ms)"
        )
    elif golden.latency_p95_ms >= thresholds.latency_p95_warn_ms:
        verdict = worst(verdict, HealthVerdict.WARN)
        notes.append(f"p95 지연 증가 {golden.latency_p95_ms:.0f}ms")

    # Open ethics alerts backlog
    if open_alerts >= thresholds.open_alerts_critical:
        verdict = worst(verdict, HealthVerdict.CRITICAL)
        notes.append(f"미처리 윤리 알림 {open_alerts}건 (임계 {thresholds.open_alerts_critical})")
    elif open_alerts >= thresholds.open_alerts_warn:
        verdict = worst(verdict, HealthVerdict.WARN)
        notes.append(f"미처리 윤리 알림 누적 {open_alerts}건")

    if verdict == HealthVerdict.OK:
        notes.append("모든 지표 정상 범위.")

    return verdict, notes


# ── human-readable rendering ───────────────────────────────────────────

_VERDICT_BADGE = {
    HealthVerdict.OK: "🟢 OK",
    HealthVerdict.WARN: "🟡 WARN",
    HealthVerdict.CRITICAL: "🔴 CRITICAL",
}


def render_digest(report: SystemReport) -> str:
    """Render a compact, scannable text digest for the human admin.

    Readability is an explicit goal: short lines, labeled sections, the verdict
    and security posture up top (what an operator needs first).
    """
    g, e = report.golden, report.engagement
    lines: list[str] = []
    lines.append(f"[buddle 시스템 리포트] {report.generated_at}  ({report.window_days}일 윈도우)")
    lines.append(f"상태: {_VERDICT_BADGE[report.verdict]}")
    lines.append("")

    lines.append("■ 보안")
    lines.append(f"  무결성 체인: {'정상' if report.integrity_ok else '검증 실패 ⚠'}")
    lines.append(f"  권한 상태: {report.authority_state}")
    lines.append(f"  미처리 윤리 알림: {report.open_ethics_alerts}건")
    lines.append("")

    lines.append("■ 트래픽/성능 (Golden Signals)")
    lines.append(f"  요청 수: {g.traffic_requests:,} ({g.requests_per_min:.1f}/분)")
    lines.append(f"  에러율: {g.error_rate:.2%}")
    lines.append(f"  지연 p50/p95: {g.latency_p50_ms:.0f} / {g.latency_p95_ms:.0f} ms")
    lines.append(f"  포화도: {g.saturation_pct:.0f}%")
    lines.append("")

    lines.append("■ 사용자 참여")
    lines.append(f"  DAU/WAU/MAU: {e.dau:,} / {e.wau:,} / {e.mau:,}")
    lines.append(f"  점착도(DAU/MAU): {e.stickiness:.1%}")
    lines.append(f"  신규 사용자: {e.new_users_in_window:,}  성장률: {e.growth_rate:+.1%}")
    lines.append(
        f"  평균 연속 사용시간: {e.avg_session_minutes:.1f}분 "
        f"(세션당 활동 {e.avg_activities_per_session:.1f}회, 총 {e.total_sessions_in_window:,}세션)"
    )
    lines.append("")

    if report.top_topics:
        topics = ", ".join(f"{t.tag}({t.count})" for t in report.top_topics)
        lines.append("■ 주요 대화 주제")
        lines.append(f"  {topics}")
        lines.append("")

    lines.append("■ 5-AI 생태계")
    for c in report.components:
        lines.append(f"  - {c.name}: {c.state} — {c.detail}")
    lines.append("")

    if report.notes:
        lines.append("■ 비고")
        for n in report.notes:
            lines.append(f"  • {n}")

    return "\n".join(lines)
