"""Insight integration tests — synthesis core, synthesizer, contracts (no DB).

DB-backed synthesize_bundle / tick integration runs in CI. Here we verify the
selective gate, recombination planning + traceability, deterministic fallback,
the synthesizer's perspective-not-conclusion stance, and service/model shapes.
"""

from __future__ import annotations

import inspect

import pytest

from buddle.ai.knowledge.synthesis import (
    BUNDLE_MIN_UNITS,
    SynthesisPlan,
    UnitView,
    fallback_summary,
    plan_synthesis,
    should_synthesize,
)

# ── selective gate ──────────────────────────────────────────────────────────


def test_small_pool_not_synthesized():
    assert not should_synthesize(BUNDLE_MIN_UNITS - 1, 0.9)


def test_large_fresh_pool_synthesized():
    assert should_synthesize(BUNDLE_MIN_UNITS, 0.9)


def test_stale_pool_not_synthesized():
    assert not should_synthesize(10, 0.0)


# ── recombination planning ──────────────────────────────────────────────────


def _units(n: int) -> list[UnitView]:
    return [UnitView(f"u{i}", f"생각 {i}", ("주제",)) for i in range(n)]


def test_plan_groups_similar_units():
    units = _units(3)

    def sim(a: str, b: str) -> float:
        return 0.9 if {a, b} == {"u0", "u1"} else 0.1

    plan = plan_synthesis(units, sim)
    # u0,u1 grouped; u2 alone
    assert [sorted(g) for g in plan.groups] == [["u0", "u1"], ["u2"]]


def test_plan_traces_all_contributors():
    units = _units(4)
    plan = plan_synthesis(units, lambda a, b: 0.0)  # nothing groups
    assert set(plan.contributing_ids) == {"u0", "u1", "u2", "u3"}
    assert len(plan.groups) == 4  # all singletons


def test_plan_collects_bridge_topics():
    units = [UnitView("u0", "g0", ("a", "b")), UnitView("u1", "g1", ("b", "c"))]
    plan = plan_synthesis(units, lambda a, b: 0.0)
    assert set(plan.bridge_topics) == {"a", "b", "c"}


# ── deterministic fallback ──────────────────────────────────────────────────


def test_fallback_summary_is_deterministic():
    units = _units(3)
    plan = plan_synthesis(units, lambda a, b: 0.0)
    s1 = fallback_summary(plan, units)
    s2 = fallback_summary(plan, units)
    assert s1 == s2


def test_fallback_does_not_assert_single_conclusion():
    units = _units(3)
    plan = plan_synthesis(units, lambda a, b: 0.0)
    _, reasoning = fallback_summary(plan, units)
    assert "단정하지 않" in reasoning  # presents perspectives


# ── synthesizer (stub) ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_stub_synthesizer_returns_summary_and_reasoning():
    from buddle.ai.knowledge.synthesizer import StubSynthesizer

    units = _units(3)
    plan = plan_synthesis(units, lambda a, b: 0.0)
    s, r = await StubSynthesizer().synthesize(topic="주제", units=units, plan=plan, language="ko")
    assert s and r


def test_llm_synthesizer_requires_endpoint():
    from buddle.ai.knowledge.synthesizer import LlmSynthesizer, SynthesisError

    with pytest.raises(SynthesisError):
        LlmSynthesizer({})


def test_synthesizer_factory_default_stub():
    from buddle.ai.knowledge.synthesizer import StubSynthesizer, get_synthesizer

    assert isinstance(get_synthesizer(), StubSynthesizer)


def test_section_parser_handles_both_and_fallback():
    from buddle.ai.knowledge.synthesizer import _parse_sections

    units = _units(1)
    plan = SynthesisPlan(groups=[["u0"]], bridge_topics=["x"], contributing_ids=["u0"])
    s, r = _parse_sections("SUMMARY: 핵심.\nREASONING: 근거.", plan, units)
    assert s == "핵심." and r == "근거."
    # empty -> deterministic fallback (non-empty)
    s2, r2 = _parse_sections("", plan, units)
    assert s2 and r2


# ── service + model contracts ───────────────────────────────────────────────


def test_synthesize_bundle_signature():
    from buddle.services import knowledge_service as ks

    assert hasattr(ks, "synthesize_bundle")
    p = inspect.signature(ks.synthesize_bundle).parameters
    assert "pool_id" in p


def test_fetch_context_has_insights_flag():
    from buddle.services import knowledge_service as ks

    p = inspect.signature(ks.fetch_context).parameters
    assert "include_insights" in p


def test_insight_bundle_model_shape():
    from buddle.db.models.insight_bundle import InsightBundle

    cols = set(InsightBundle.__table__.columns.keys())
    assert {
        "pool_id",
        "topic",
        "summary",
        "reasoning_trace",
        "contributing_unit_ids",
        "visibility",
        "status",
        "integrity_sig",
    } <= cols
