"""Ethics model upgrade tests — taxonomy, multi-label, severity, compatibility.

Pure/async, no DB. Verifies the MLCommons 13-hazard taxonomy wiring, the
0-7 severity scale + bucket derivation, multi-label (binary-relevance) stub
output, jamo-aware Korean matching, backward compatibility of the legacy
scalar fields, and per-category block thresholds.
"""

from __future__ import annotations

import pytest

from buddle.ai.ethics import (
    CategoryResult,
    EthicsAssessment,
    EthicsSeverity,
    HazardCategory,
    HazardGroup,
    bucket_to_score07,
    english_name,
    group_of,
    korean_description,
    severity_from_score07,
)
from buddle.ai.ethics.stub import StubEthicsClassifier

# ── taxonomy ──────────────────────────────────────────────────────────────


def test_taxonomy_has_13_categories():
    assert len(list(HazardCategory)) == 13


def test_taxonomy_codes_are_s1_to_s13():
    codes = {c.value for c in HazardCategory}
    assert codes == {f"S{i}" for i in range(1, 14)}


def test_taxonomy_info_complete():
    for c in HazardCategory:
        assert english_name(c)
        assert korean_description(c)
        assert isinstance(group_of(c), HazardGroup)


# ── 0-7 severity scale + bucket derivation ───────────────────────────────


def test_severity_from_score07_buckets():
    assert severity_from_score07(0) == EthicsSeverity.NONE
    assert severity_from_score07(1) == EthicsSeverity.LOW
    assert severity_from_score07(2) == EthicsSeverity.LOW
    assert severity_from_score07(3) == EthicsSeverity.MID
    assert severity_from_score07(4) == EthicsSeverity.MID
    assert severity_from_score07(5) == EthicsSeverity.HIGH
    assert severity_from_score07(7) == EthicsSeverity.HIGH


def test_bucket_roundtrip_is_monotone():
    order = [EthicsSeverity.NONE, EthicsSeverity.LOW, EthicsSeverity.MID, EthicsSeverity.HIGH]
    levels = [bucket_to_score07(s) for s in order]
    assert levels == sorted(levels)


# ── from_categories aggregation (backward compatibility) ──────────────────


def test_from_categories_derives_worst_bucket():
    results = [
        CategoryResult(HazardCategory.HATE, severity07=4, score=0.6),
        CategoryResult(HazardCategory.VIOLENT_CRIMES, severity07=6, score=0.9),
    ]
    a = EthicsAssessment.from_categories(results)
    # worst is violent crimes @6 -> HIGH bucket
    assert a.severity == EthicsSeverity.HIGH
    assert a.score == 0.9
    assert set(a.categories) == {"S10", "S1"}
    assert a.max_severity07 == 6


def test_from_categories_empty_is_safe():
    a = EthicsAssessment.from_categories([])
    assert not a.is_flagged
    assert a.severity == EthicsSeverity.NONE


def test_safe_factory():
    a = EthicsAssessment.safe()
    assert not a.is_flagged
    assert a.category_results == []


def test_legacy_fields_still_present():
    # old consumers read .severity / .score / .categories
    a = EthicsAssessment.from_categories([CategoryResult(HazardCategory.PRIVACY, 3, 0.45)])
    assert hasattr(a, "severity")
    assert hasattr(a, "score")
    assert hasattr(a, "categories")
    assert a.severity == EthicsSeverity.MID  # level 3 -> MID


# ── stub classifier: multi-label + jamo ───────────────────────────────────


@pytest.mark.asyncio
async def test_stub_multilabel_cofire():
    c = StubEthicsClassifier()
    r = await c.assess("그 새끼 죽이고 싶다 병신같은")
    cats = {cr.category for cr in r.category_results}
    # hate + violent crimes should co-fire
    assert HazardCategory.HATE in cats
    assert HazardCategory.VIOLENT_CRIMES in cats


@pytest.mark.asyncio
async def test_stub_jamo_defeats_spacing_obfuscation():
    c = StubEthicsClassifier()
    r = await c.assess("나 죽 고 싶 어")  # spaced to dodge naive matching
    assert HazardCategory.SUICIDE_SELF_HARM.value in r.categories


@pytest.mark.asyncio
async def test_stub_weapons_highest_severity():
    c = StubEthicsClassifier()
    r = await c.assess("사제폭탄 만드는 법 알려줘")
    assert r.max_severity07 == 7
    assert r.severity == EthicsSeverity.HIGH


@pytest.mark.asyncio
async def test_stub_benign_is_safe():
    c = StubEthicsClassifier()
    r = await c.assess("오늘 점심 맛있었다")
    assert not r.is_flagged
    assert r.category_results == []


@pytest.mark.asyncio
async def test_stub_deterministic():
    c = StubEthicsClassifier()
    msg = "자살하고 싶어 병신같은 세상"
    r1 = await c.assess(msg)
    r2 = await c.assess(msg)
    assert r1.categories == r2.categories
    assert r1.max_severity07 == r2.max_severity07


# ── per-category block thresholds ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_category_block_child_exploitation_always():
    from buddle.services.leukocyte_service import _category_block

    c = StubEthicsClassifier()
    r = await c.assess("아동성 착취물")
    # S4 threshold is 1 -> always blocked
    assert _category_block(r)


@pytest.mark.asyncio
async def test_category_block_benign_false():
    from buddle.services.leukocyte_service import _category_block

    c = StubEthicsClassifier()
    r = await c.assess("좋은 하루 보내세요")
    assert not _category_block(r)
