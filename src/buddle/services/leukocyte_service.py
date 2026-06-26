"""Leukocyte service — ethics monitoring + importance modulation.

Responsibilities:
  1. assess_post: run the ethics classifier on a post's content; on a flagged
     result, (a) raise an EthicsAlert for the human-admin queue and (b) apply a
     negative importance contribution scaled to severity.
  2. apply_mention / apply_like / apply_report: positive/negative importance
     contributions from downstream signals.

Graceful degradation: if the ethics backend errors, assess_post logs and
treats the content as unflagged (NONE) — availability over hard-blocking, the
same posture as the persona/embedding fallbacks. A failed classification never
breaks post creation.

The leukocyte does NOT delete or hard-block content. It annotates (alerts) and
de-weights (importance). The post pipeline decides visibility suppression based
on ethics_block_severity; everything is still stored for audit.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from buddle.ai.ethics import (
    EthicsAssessment,
    EthicsError,
    EthicsSeverity,
    get_ethics_classifier,
    severity_rank,
)
from buddle.config import get_settings
from buddle.core.logging import get_logger
from buddle.db.models.ethics_alert import EthicsAlert
from buddle.services.importance_service import (
    add_contribution as _add_contribution,
)

log = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class LeukocyteResult:
    """Outcome of assessing a post."""

    assessment: EthicsAssessment
    alert_raised: bool
    importance_delta: float
    should_suppress: bool  # severity >= configured block threshold


def _ethics_delta(severity: EthicsSeverity) -> float:
    s = get_settings()
    return {
        EthicsSeverity.NONE: 0.0,
        EthicsSeverity.LOW: s.importance_delta_ethics_low,
        EthicsSeverity.MID: s.importance_delta_ethics_mid,
        EthicsSeverity.HIGH: s.importance_delta_ethics_high,
    }[severity]


def _block_severity() -> EthicsSeverity:
    return EthicsSeverity(get_settings().ethics_block_severity)


def _category_block(assessment: EthicsAssessment) -> bool:
    """True if any fired category meets its configured per-category 0-7 block
    threshold. Lets the most serious hazards block at a lower bar."""
    levels = get_settings().ethics_category_block_levels
    for cr in assessment.category_results:
        threshold = levels.get(cr.category.value)
        if threshold is not None and cr.severity07 >= threshold:
            return True
    return False


async def assess_post(
    db: AsyncSession,
    post_id: uuid.UUID,
    content: str,
    *,
    commit: bool = False,
) -> LeukocyteResult:
    """Assess a post's content. Raises an alert + applies an importance penalty
    when flagged. Returns a LeukocyteResult describing what happened.

    `commit=False` lets the caller fold this into the post-creation
    transaction; importance contribution is flushed but not committed.
    """
    classifier = get_ethics_classifier()
    try:
        assessment = await classifier.assess(content)
    except EthicsError as e:
        log.warning("leukocyte.assess_failed", post_id=str(post_id), error=str(e))
        assessment = EthicsAssessment(severity=EthicsSeverity.NONE, score=0.0)

    alert_raised = False
    importance_delta = 0.0
    should_suppress = False

    if assessment.is_flagged:
        # 1. Alert for human review
        db.add(
            EthicsAlert(
                target_id=post_id,
                target_type="post",
                severity=assessment.severity.value,
                reason=assessment.reason,
            )
        )
        alert_raised = True

        # 2. Negative importance contribution scaled to severity
        importance_delta = _ethics_delta(assessment.severity)
        if importance_delta != 0.0:
            await _add_contribution(
                db,
                post_id,
                source=f"ethics:{assessment.severity.value}",
                delta=importance_delta,
                commit=False,
            )

        # 3. Visibility suppression decision. Either the bucket policy fires,
        #    OR a high-severity category crosses its per-category threshold
        #    (e.g. child exploitation / weapons block at a lower bar).
        bucket_suppress = severity_rank(assessment.severity) >= severity_rank(_block_severity())
        category_suppress = _category_block(assessment)
        should_suppress = bucket_suppress or category_suppress

    if commit:
        await db.commit()

    log.info(
        "leukocyte.assessed",
        post_id=str(post_id),
        severity=assessment.severity.value,
        categories=assessment.categories,
        alert_raised=alert_raised,
        suppress=should_suppress,
    )
    return LeukocyteResult(
        assessment=assessment,
        alert_raised=alert_raised,
        importance_delta=importance_delta,
        should_suppress=should_suppress,
    )


# ── downstream importance signals ───────────────────────────────────────


async def apply_mention(db: AsyncSession, post_id: uuid.UUID, *, commit: bool = False) -> None:
    """A persona received this post via distribution — a positive 'mention'."""
    delta = get_settings().importance_delta_mention
    await _add_contribution(db, post_id, source="mention", delta=delta, commit=commit)


async def apply_like(db: AsyncSession, post_id: uuid.UUID, *, commit: bool = True) -> None:
    delta = get_settings().importance_delta_like
    await _add_contribution(db, post_id, source="like", delta=delta, commit=commit)


async def apply_report(
    db: AsyncSession,
    post_id: uuid.UUID,
    *,
    reason: str | None = None,
    commit: bool = True,
) -> EthicsAlert:
    """A user reported the post: negative importance + an alert for review."""
    delta = get_settings().importance_delta_report
    await _add_contribution(db, post_id, source="report", delta=delta, commit=False)
    alert = EthicsAlert(
        target_id=post_id,
        target_type="post",
        severity="mid",
        reason=reason or "user report",
    )
    db.add(alert)
    if commit:
        await db.commit()
        await db.refresh(alert)
    return alert


# Safe fallback shown to the user when a persona's own reply is blocked by the
# response-side gate. Kept generic + caring; never echoes the unsafe content.
_RESPONSE_BLOCKED_FALLBACK = (
    "미안해요, 그 부분은 제가 도와드리기 어려운 내용이라 여기서는 답하지 않을게요. "
    "다른 이야기로 함께 이어가요."
)


@dataclass(frozen=True, slots=True)
class ResponseScreenResult:
    """Outcome of screening a persona's generated reply (output-side gate)."""

    allowed: bool
    content: str  # original if allowed, safe fallback if blocked
    assessment: EthicsAssessment


async def screen_response(text: str) -> ResponseScreenResult:
    """Output-side ethics gate: screen a persona's GENERATED reply before it is
    shown. Llama Guard literature shows response-side classification is more
    robust to adversarial prompts than input-side alone, so this is a second
    line of defense complementing assess_post (input) and the conscience gate.

    Stateless (no DB write) and fail-open on classifier error: if the backend
    is down we don't block normal replies, matching assess_post's graceful
    degradation. Blocking decision reuses the same bucket + per-category policy.
    """
    classifier = get_ethics_classifier()
    try:
        # Llama Guard can score an assistant turn specifically; other backends
        # use their single-arg assess. Detect support without hard coupling.
        assess = classifier.assess
        try:
            assessment = await assess(text, role="assistant")
        except TypeError:
            assessment = await assess(text)
    except EthicsError as e:
        log.warning("leukocyte.screen_response_failed", error=str(e))
        return ResponseScreenResult(allowed=True, content=text, assessment=EthicsAssessment.safe())

    blocked = assessment.is_flagged and (
        severity_rank(assessment.severity) >= severity_rank(_block_severity())
        or _category_block(assessment)
    )
    if blocked:
        log.info("leukocyte.response_blocked", categories=assessment.categories)
        return ResponseScreenResult(
            allowed=False, content=_RESPONSE_BLOCKED_FALLBACK, assessment=assessment
        )
    return ResponseScreenResult(allowed=True, content=text, assessment=assessment)
