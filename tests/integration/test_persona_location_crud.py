"""Persona location-in-CRUD + selection optimization equivalence (no DB).

Verifies the location fields are part of persona create/update schemas (so the
proximity feature can be configured in one place) and that the single-pass
similarity stats are byte-for-byte equivalent to the previous two-pass code.
"""

from __future__ import annotations

import random

import pytest
from pydantic import ValidationError as PydanticValidationError

from buddle.schemas.persona import PersonaCreate, PersonaUpdate
from buddle.services.knowledge_service import (
    REDUNDANCY_SIM,
    _max_cosine_sim,
    _sim_stats,
)

# ── location merged into persona CRUD ───────────────────────────────────────


def test_create_accepts_location():
    c = PersonaCreate(
        name="초록",
        model_key="stub-ko",
        location_sharing=True,
        location_lat=37.5,
        location_lon=127.0,
    )
    assert c.location_sharing is True
    assert c.location_lat == 37.5
    assert c.location_lon == 127.0


def test_create_location_defaults_off():
    c = PersonaCreate(name="물결", model_key="stub-ko")
    assert c.location_sharing is False
    assert c.location_lat is None


def test_update_accepts_location_fields():
    u = PersonaUpdate(location_sharing=False)
    assert u.location_sharing is False


def test_location_lat_range_validated():
    with pytest.raises(PydanticValidationError):
        PersonaCreate(name="x", model_key="stub-ko", location_lat=200.0)
    with pytest.raises(PydanticValidationError):
        PersonaCreate(name="x", model_key="stub-ko", location_lon=-999.0)


# ── optimization equivalence (function unchanged, faster) ───────────────────


def test_sim_stats_matches_two_pass_random():
    rng = random.Random(7)
    for _ in range(500):
        dim = 8
        vec = [rng.uniform(-1, 1) for _ in range(dim)]
        others = [[rng.uniform(-1, 1) for _ in range(dim)] for _ in range(rng.randint(0, 8))]
        old_max = _max_cosine_sim(vec, others)
        old_dupes = sum(1 for o in others if _max_cosine_sim(vec, [o]) >= REDUNDANCY_SIM)
        new_max, new_dupes, _mean = _sim_stats(vec, others, dup_threshold=REDUNDANCY_SIM)
        assert abs(old_max - new_max) < 1e-9
        assert old_dupes == new_dupes


def test_sim_stats_empty():
    assert _sim_stats([1.0, 2.0], [], dup_threshold=0.9) == (0.0, 0, 0.0)


def test_sim_stats_counts_duplicates():
    v = [1.0, 0.0]
    others = [[1.0, 0.0], [1.0, 0.0], [0.0, 1.0]]  # two identical, one orthogonal
    max_sim, dupes, mean = _sim_stats(v, others, dup_threshold=REDUNDANCY_SIM)
    assert abs(max_sim - 1.0) < 1e-9
    assert dupes == 2
    assert 0.0 <= mean <= 1.0  # mean positive cohesion in range
