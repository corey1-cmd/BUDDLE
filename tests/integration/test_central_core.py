"""Pure central-manager core tests: health verdict + policy auto-tune guardrails.

No DB. Locks in the security-first verdict (integrity failure / TECH_ELEVATED
always CRITICAL) and the auto-tuner's safety guardrails (skip when unhealthy,
bounded step, renormalization).
"""

from __future__ import annotations

import pytest

from buddle.ai.central import (
    AIComponentStatus,
    EngagementMetrics,
    GoldenSignals,
    HealthThresholds,
    HealthVerdict,
    SystemReport,
    TopicCount,
    compute_verdict,
    propose_weights,
    render_digest,
    worst,
)
from buddle.ai.central.autotune import MAX_STEP, W_MAX, W_MIN

TH = HealthThresholds(
    error_rate_warn=0.02,
    error_rate_critical=0.05,
    latency_p95_warn_ms=800,
    latency_p95_critical_ms=2000,
    open_alerts_warn=5,
    open_alerts_critical=20,
)

GOOD = GoldenSignals(
    traffic_requests=1000,
    requests_per_min=10.0,
    error_rate=0.01,
    latency_p50_ms=50,
    latency_p95_ms=200,
    saturation_pct=30,
)


# ── verdict ─────────────────────────────────────────────────────────────


def test_all_green_is_ok():
    v, notes = compute_verdict(
        golden=GOOD,
        open_alerts=0,
        authority_state="normal",
        integrity_ok=True,
        thresholds=TH,
    )
    assert v == HealthVerdict.OK
    assert notes


def test_integrity_failure_is_always_critical():
    v, _ = compute_verdict(
        golden=GOOD,
        open_alerts=0,
        authority_state="normal",
        integrity_ok=False,
        thresholds=TH,
    )
    assert v == HealthVerdict.CRITICAL


def test_tech_elevated_is_always_critical():
    v, _ = compute_verdict(
        golden=GOOD,
        open_alerts=0,
        authority_state="tech_elevated",
        integrity_ok=True,
        thresholds=TH,
    )
    assert v == HealthVerdict.CRITICAL


def test_high_error_rate_warns():
    g = GoldenSignals(
        traffic_requests=1000,
        requests_per_min=10,
        error_rate=0.03,
        latency_p50_ms=50,
        latency_p95_ms=200,
        saturation_pct=30,
    )
    v, _ = compute_verdict(
        golden=g,
        open_alerts=0,
        authority_state="normal",
        integrity_ok=True,
        thresholds=TH,
    )
    assert v == HealthVerdict.WARN


def test_critical_error_rate_is_critical():
    g = GoldenSignals(
        traffic_requests=1000,
        requests_per_min=10,
        error_rate=0.08,
        latency_p50_ms=50,
        latency_p95_ms=200,
        saturation_pct=30,
    )
    v, _ = compute_verdict(
        golden=g,
        open_alerts=0,
        authority_state="normal",
        integrity_ok=True,
        thresholds=TH,
    )
    assert v == HealthVerdict.CRITICAL


def test_alert_backlog_escalates():
    v_warn, _ = compute_verdict(
        golden=GOOD,
        open_alerts=6,
        authority_state="normal",
        integrity_ok=True,
        thresholds=TH,
    )
    assert v_warn == HealthVerdict.WARN
    v_crit, _ = compute_verdict(
        golden=GOOD,
        open_alerts=25,
        authority_state="normal",
        integrity_ok=True,
        thresholds=TH,
    )
    assert v_crit == HealthVerdict.CRITICAL


def test_worst_helper():
    assert worst(HealthVerdict.OK, HealthVerdict.WARN) == HealthVerdict.WARN
    assert worst(HealthVerdict.WARN, HealthVerdict.CRITICAL) == HealthVerdict.CRITICAL
    assert worst(HealthVerdict.OK, HealthVerdict.OK) == HealthVerdict.OK


# ── auto-tune guardrails ────────────────────────────────────────────────


def test_autotune_skips_when_unhealthy():
    p = propose_weights(
        current_alpha=0.4,
        current_beta=0.4,
        current_gamma=0.2,
        stickiness=0.01,
        avg_session_minutes=0.5,
        healthy=False,
    )
    assert not p.changed
    assert p.alpha == 0.4 and p.beta == 0.4 and p.gamma == 0.2


def test_autotune_skips_when_engagement_healthy():
    p = propose_weights(
        current_alpha=0.4,
        current_beta=0.4,
        current_gamma=0.2,
        stickiness=0.5,
        avg_session_minutes=12.0,
        healthy=True,
    )
    assert not p.changed


def test_autotune_nudges_beta_when_weak_and_healthy():
    p = propose_weights(
        current_alpha=0.4,
        current_beta=0.4,
        current_gamma=0.2,
        stickiness=0.05,
        avg_session_minutes=1.0,
        healthy=True,
    )
    assert p.changed
    assert p.beta > 0.4  # beta nudged up
    # renormalized to sum 1
    assert p.alpha + p.beta + p.gamma == pytest.approx(1.0)
    # within guardrails
    for w in (p.alpha, p.beta, p.gamma):
        assert W_MIN <= w <= W_MAX


def test_autotune_step_is_bounded():
    # Even from an extreme starting point, one cycle cannot exceed the cap by
    # much after renormalization (sanity check on monotonic, small movement).
    p = propose_weights(
        current_alpha=0.45,
        current_beta=0.45,
        current_gamma=0.10,
        stickiness=0.05,
        avg_session_minutes=1.0,
        healthy=True,
    )
    assert p.changed
    assert p.beta <= 0.45 + MAX_STEP + 0.05  # bounded by step + renorm slack


# ── rendering ────────────────────────────────────────────────────────────


def test_render_digest_contains_key_sections():
    e = EngagementMetrics(
        dau=100,
        wau=400,
        mau=1000,
        stickiness=0.1,
        new_users_in_window=50,
        growth_rate=0.05,
        avg_session_minutes=4.2,
        avg_activities_per_session=3.1,
        total_sessions_in_window=500,
    )
    r = SystemReport(
        generated_at="2026-05-18T06:30:00+00:00",
        window_days=7,
        verdict=HealthVerdict.OK,
        golden=GOOD,
        engagement=e,
        components=[AIComponentStatus(name="페르소나", state="ok", detail="x")],
        top_topics=[TopicCount(tag="여행", count=42)],
        open_ethics_alerts=0,
        authority_state="normal",
        integrity_ok=True,
        notes=["정상"],
    )
    d = render_digest(r)
    assert "시스템 리포트" in d
    assert "보안" in d
    assert "Golden Signals" in d
    assert "사용자 참여" in d
    assert "여행" in d
    assert "5-AI 생태계" in d
