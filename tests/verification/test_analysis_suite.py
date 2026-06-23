"""Engineering-style verification suite, adapted to a software system.

The user asked for FEM / CFD / convergence / sensitivity / extreme-case
analyses. Those originate in physical simulation, so we apply their underlying
mathematical intent to this codebase:

  - Convergence test: as an input grows, does an output metric converge to a
    stable bound rather than diverge? (importance tanh, decision scores)
  - Sensitivity analysis: do outputs respond monotonically and proportionally
    to parameter perturbations? (persona dispositions, health thresholds,
    importance kappa)
  - Extreme-case test: does the system stay stable on extreme inputs (empty,
    huge, unicode, adversarial)?
  - Boundary-value test: correctness exactly at decision thresholds.
  - "FEM/CFD" intent (domain decomposition + assembly): the EKB pipeline
    decomposes a message into cognitive sub-stages and reassembles them; we
    verify the decomposition is consistent and the assembled result is stable.

All pure / offline; no DB. These complement the per-module unit tests.
"""

from __future__ import annotations

import itertools

import pytest

from buddle.ai.central import (
    GoldenSignals,
    HealthThresholds,
    HealthVerdict,
    compute_verdict,
)
from buddle.ai.cognition import (
    PersonaDispositions,
    ResponseStrategy,
    process_information,
    run_cognition,
)
from buddle.ai.importance import ImportanceParams, normalize
from buddle.ai.technician import AuthorityParams, decide_state

# ════════════════════════════════════════════════════════════════════════
# 1. CONVERGENCE TESTS
# ════════════════════════════════════════════════════════════════════════

IMP = ImportanceParams(i_max=1.0, kappa=50.0)


def test_convergence_importance_saturates():
    """As raw importance grows unboundedly, normalized value converges to i_max
    (does not diverge). Classic convergence-to-asymptote check."""
    raws = [10, 100, 1_000, 10_000, 100_000, 1_000_000]
    vals = [normalize(r, IMP) for r in raws]
    # monotone increasing, strictly bounded by i_max, converging
    assert all(b >= a for a, b in itertools.pairwise(vals))
    assert all(v <= IMP.i_max for v in vals)
    # successive deltas shrink toward 0 (convergence)
    deltas = [b - a for a, b in itertools.pairwise(vals)]
    assert all(deltas[i + 1] <= deltas[i] + 1e-9 for i in range(len(deltas) - 1))
    assert deltas[-1] < 1e-3  # effectively converged


def test_convergence_decision_scores_bounded():
    """Decision candidate scores stay finite and bounded as affect intensity
    grows (many emotional tokens) — no score blow-up."""
    messages = [
        "기뻐",
        "너무 기뻐 행복해",
        "너무너무 기뻐 행복해 신나 최고 사랑 감사",
        " ".join(["행복"] * 50),
    ]
    for msg in messages:
        _, decision, _ = run_cognition(msg)
        for c in decision.candidates:
            assert 0.0 <= c.score <= 3.0  # finite, sane upper bound


# ════════════════════════════════════════════════════════════════════════
# 2. SENSITIVITY ANALYSIS
# ════════════════════════════════════════════════════════════════════════


def test_sensitivity_importance_kappa_monotonic():
    """Smaller kappa => faster saturation. At a fixed raw, normalized value is
    monotonically decreasing in kappa."""
    raw = 30.0
    kappas = [10.0, 25.0, 50.0, 100.0, 200.0]
    vals = [normalize(raw, ImportanceParams(i_max=1.0, kappa=k)) for k in kappas]
    assert all(b <= a for a, b in itertools.pairwise(vals))


def test_sensitivity_persona_warmth_monotonic():
    """Sweeping warmth upward must not DECREASE the celebrate score for good
    news (monotone response to the parameter)."""
    info = process_information("나 합격했어!")
    from buddle.ai.cognition import decide

    scores = []
    for w in [0.0, 0.25, 0.5, 0.75, 1.0]:
        d = decide(info, dispositions=PersonaDispositions(warmth=w))
        s = next(c.score for c in d.candidates if c.strategy == ResponseStrategy.CELEBRATE)
        scores.append(s)
    assert all(b >= a - 1e-9 for a, b in itertools.pairwise(scores))


def test_sensitivity_informativeness_monotonic():
    info = process_information("이거 어떻게 해?")
    from buddle.ai.cognition import decide

    scores = []
    for v in [0.0, 0.5, 1.0]:
        d = decide(info, dispositions=PersonaDispositions(informativeness=v))
        s = next(c.score for c in d.candidates if c.strategy == ResponseStrategy.INFORM)
        scores.append(s)
    assert scores[0] <= scores[1] <= scores[2]


def test_sensitivity_health_threshold_response():
    """Verdict must worsen monotonically as error rate crosses thresholds."""
    th = HealthThresholds(
        error_rate_warn=0.02,
        error_rate_critical=0.05,
        latency_p95_warn_ms=800,
        latency_p95_critical_ms=2000,
        open_alerts_warn=5,
        open_alerts_critical=20,
    )
    rank = {HealthVerdict.OK: 0, HealthVerdict.WARN: 1, HealthVerdict.CRITICAL: 2}
    prev = -1
    for err in [0.0, 0.02, 0.05, 0.2]:
        g = GoldenSignals(
            traffic_requests=100,
            requests_per_min=1.0,
            error_rate=err,
            latency_p50_ms=10,
            latency_p95_ms=100,
            saturation_pct=10,
        )
        v, _ = compute_verdict(
            golden=g,
            open_alerts=0,
            authority_state="normal",
            integrity_ok=True,
            thresholds=th,
        )
        assert rank[v] >= prev  # monotonic non-decreasing severity
        prev = rank[v]


# ════════════════════════════════════════════════════════════════════════
# 3. BOUNDARY-VALUE TESTS
# ════════════════════════════════════════════════════════════════════════


def test_boundary_authority_exact_equality_stays_normal():
    """Authority crossing is strict (>). Exactly equal => NORMAL (boundary)."""
    p = AuthorityParams(
        central_base=100.0,
        technician_base=0.0,
        debit_unverified=10.0,
        credit_restoration=10.0,
    )
    # central = 100 - 10*10 = 0 ; technician = 0 -> equal -> NORMAL
    from buddle.ai.technician.authority import AuthorityState

    assert decide_state(p, unverified_count=10, restoration_count=0) == AuthorityState.NORMAL
    # one more unverified tips it
    assert decide_state(p, unverified_count=11, restoration_count=0).value == "tech_elevated"


def test_boundary_health_exactly_at_warn():
    th = HealthThresholds(
        error_rate_warn=0.02,
        error_rate_critical=0.05,
        latency_p95_warn_ms=800,
        latency_p95_critical_ms=2000,
        open_alerts_warn=5,
        open_alerts_critical=20,
    )
    g = GoldenSignals(
        traffic_requests=100,
        requests_per_min=1.0,
        error_rate=0.02,
        latency_p50_ms=10,
        latency_p95_ms=100,
        saturation_pct=10,
    )
    v, _ = compute_verdict(
        golden=g,
        open_alerts=0,
        authority_state="normal",
        integrity_ok=True,
        thresholds=th,
    )
    assert v == HealthVerdict.WARN  # >= warn threshold


def test_boundary_clarity_threshold():
    """needs_clarification flips around the clarity threshold (0.35)."""
    vague = process_information("어")
    clear = process_information("다음 주 화요일 부산 여행 맛집 세 곳만 구체적으로 추천해줘")
    assert vague.needs_clarification
    assert not clear.needs_clarification


# ════════════════════════════════════════════════════════════════════════
# 4. EXTREME-CASE TESTS
# ════════════════════════════════════════════════════════════════════════


def test_extreme_empty_string():
    info = process_information("")
    assert info.raw_len == 0
    # must not crash; produces a defined (low-clarity) result
    _, decision, block = run_cognition("")
    assert decision.chosen in set(ResponseStrategy)
    assert block


def test_extreme_whitespace_only():
    _, decision, _ = run_cognition("     \n\t   ")
    assert decision.chosen in set(ResponseStrategy)


def test_extreme_very_long_input():
    huge = "행복 " * 5000  # ~10k tokens
    info = process_information(huge)
    # attention stays bounded (selective filter caps salient tokens)
    assert len(info.attention.salient_tokens) <= 12
    assert len(info.salient_points) <= 6


def test_extreme_unicode_and_emoji():
    for msg in ["😀😀😀🎉", "ＦＵＬＬＷＩＤＴＨ", "ñöñ-ascii café", "🇰🇷 한글 mixed 123"]:  # noqa: RUF001
        info = process_information(msg)
        assert info.raw_len >= 0
        _, decision, _ = run_cognition(msg)
        assert decision.chosen in set(ResponseStrategy)


def test_extreme_only_punctuation():
    _, decision, _ = run_cognition("!@#$%^&*()")
    assert decision.chosen in set(ResponseStrategy)


def test_extreme_normalize_infinities_guarded():
    """normalize must stay bounded even for absurd magnitudes."""
    assert normalize(1e308, IMP) <= IMP.i_max
    assert normalize(-1e308, IMP) >= -IMP.i_max


def test_extreme_negative_counts_clamped():
    p = AuthorityParams(
        central_base=100.0,
        technician_base=0.0,
        debit_unverified=10.0,
        credit_restoration=10.0,
    )
    # negative inputs must not flip state nonsensically
    from buddle.ai.technician.authority import AuthorityState

    assert decide_state(p, unverified_count=-100, restoration_count=-100) == AuthorityState.NORMAL


# ════════════════════════════════════════════════════════════════════════
# 5. "FEM/CFD" INTENT: decomposition consistency + assembled stability
# ════════════════════════════════════════════════════════════════════════


def test_decomposition_stage_outputs_consistent():
    """The pipeline decomposes a message into sub-stages then reassembles.
    Verify the assembled decision is consistent with the stage outputs (no
    contradiction between comprehension and choice)."""
    _, decision, _ = run_cognition("나 시험 합격했어 너무 기뻐!")
    # comprehension said positive share-news -> assembled choice must be a
    # positive strategy, never comfort/clarify
    assert decision.chosen in {ResponseStrategy.CELEBRATE, ResponseStrategy.CONVERSE}


def test_reassembly_deterministic_across_runs():
    """Same message + same dispositions => identical assembled result every
    run (mesh-independence analogue: result independent of repetition)."""
    disp = PersonaDispositions(warmth=0.7, informativeness=0.6)
    runs = [run_cognition("나 합격했어!", dispositions=disp)[1].chosen for _ in range(20)]
    assert len(set(runs)) == 1  # fully stable


@pytest.mark.parametrize(
    "msg,expected",
    [
        ("나 합격했어!", ResponseStrategy.CELEBRATE),
        ("너무 외롭고 힘들어", ResponseStrategy.COMFORT),
        ("이거 어떻게 해?", ResponseStrategy.INFORM),
        ("이 버그 고쳐줘", ResponseStrategy.ASSIST),
    ],
)
def test_assembled_choice_matches_theory(msg, expected):  # type: ignore[no-untyped-def]
    """Accuracy check: assembled output matches the EKB-theoretic expectation
    for canonical intents."""
    _, decision, _ = run_cognition(msg)
    assert decision.chosen == expected
