"""Ethics classifier (stub) tests."""

from __future__ import annotations

import pytest

from buddle.ai.ethics import EthicsSeverity, StubEthicsClassifier, severity_rank

pytestmark = pytest.mark.asyncio


async def test_clean_content_not_flagged():
    c = StubEthicsClassifier()
    a = await c.assess("오늘 날씨가 좋아서 산책을 했다")
    assert a.severity == EthicsSeverity.NONE
    assert not a.is_flagged
    assert a.score == 0.0


async def test_self_harm_is_high():
    c = StubEthicsClassifier()
    a = await c.assess("자살 하고 싶다는 생각이 든다")
    assert a.severity == EthicsSeverity.HIGH
    assert a.is_flagged
    assert "S11" in a.categories  # Suicide & Self-Harm
    assert a.score > 0.85


async def test_hate_is_mid():
    c = StubEthicsClassifier()
    a = await c.assess("이 병신아 꺼져")
    assert a.severity == EthicsSeverity.MID
    assert "S10" in a.categories  # Hate


async def test_specialized_advice_is_low():
    c = StubEthicsClassifier()
    a = await c.assess("이 약물복용량 그냥 늘려도 돼")
    assert a.severity == EthicsSeverity.LOW
    assert "S6" in a.categories  # Specialized Advice


async def test_worst_severity_wins_when_multiple_fire():
    c = StubEthicsClassifier()
    a = await c.assess("이 약물복용량 늘리고 자살 관련 내용")
    # specialized advice (low) + self_harm (high) -> high
    assert a.severity == EthicsSeverity.HIGH
    assert {"S6", "S11"}.issubset(set(a.categories))


def test_severity_rank_ordering():
    assert (
        severity_rank(EthicsSeverity.NONE)
        < severity_rank(EthicsSeverity.LOW)
        < severity_rank(EthicsSeverity.MID)
        < severity_rank(EthicsSeverity.HIGH)
    )
