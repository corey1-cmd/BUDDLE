"""Policy auto-tuning proposals (pure).

The central manager may *propose* small, bounded adjustments to the mediator
distribution policy based on observed signals — but always within hard
guardrails, and never in a way that compromises safety. Auto-tuning is
advisory by default: it returns a proposal the service can apply or surface to
the human admin.

Guardrails (the important part — an autonomous tuner must not be able to push
the system into a degenerate state):
  - weights stay within [W_MIN, W_MAX]
  - the three weights are renormalized to sum to 1
  - step size per cycle is capped (no large swings)
  - tuning is SKIPPED entirely when the system is unhealthy/elevated (don't
    optimize engagement while potentially compromised)

This mirrors the fail-safe posture used elsewhere: when in doubt, do nothing.
"""

from __future__ import annotations

from dataclasses import dataclass

W_MIN = 0.05
W_MAX = 0.90
MAX_STEP = 0.05


@dataclass(frozen=True, slots=True)
class WeightProposal:
    alpha: float
    beta: float
    gamma: float
    changed: bool
    rationale: str


def _clamp(x: float) -> float:
    return max(W_MIN, min(W_MAX, x))


def _renormalize(a: float, b: float, g: float) -> tuple[float, float, float]:
    total = a + b + g
    if total <= 0:
        # degenerate; fall back to uniform
        return (1 / 3, 1 / 3, 1 / 3)
    return (a / total, b / total, g / total)


def propose_weights(
    *,
    current_alpha: float,
    current_beta: float,
    current_gamma: float,
    stickiness: float,
    avg_session_minutes: float,
    healthy: bool,
) -> WeightProposal:
    """Propose a bounded weight adjustment.

    Heuristic (intentionally conservative and easy to reason about):
      - If engagement is weak (low stickiness AND short sessions), nudge weight
        toward content similarity (beta) so distribution surfaces more
        relevant content — a small step only.
      - Otherwise, leave weights unchanged.

    Returns changed=False (and identical weights) when the system is unhealthy,
    or when no adjustment is warranted.
    """
    if not healthy:
        return WeightProposal(
            alpha=current_alpha,
            beta=current_beta,
            gamma=current_gamma,
            changed=False,
            rationale="시스템 비정상/권한 상승 상태 — 자동 튜닝 보류 (안전 우선).",
        )

    weak_engagement = stickiness < 0.15 and avg_session_minutes < 3.0
    if not weak_engagement:
        return WeightProposal(
            alpha=current_alpha,
            beta=current_beta,
            gamma=current_gamma,
            changed=False,
            rationale="참여 지표 양호 — 가중치 조정 불필요.",
        )

    # Nudge beta up by MAX_STEP, pull equally from alpha/gamma, clamp, renorm.
    new_beta = _clamp(current_beta + MAX_STEP)
    new_alpha = _clamp(current_alpha - MAX_STEP / 2)
    new_gamma = _clamp(current_gamma - MAX_STEP / 2)
    new_alpha, new_beta, new_gamma = _renormalize(new_alpha, new_beta, new_gamma)

    return WeightProposal(
        alpha=round(new_alpha, 4),
        beta=round(new_beta, 4),
        gamma=round(new_gamma, 4),
        changed=True,
        rationale=(
            f"참여 약함(점착도 {stickiness:.1%}, 평균 세션 {avg_session_minutes:.1f}분) "
            "→ 콘텐츠 유사도 가중치 소폭 상향."
        ),
    )
