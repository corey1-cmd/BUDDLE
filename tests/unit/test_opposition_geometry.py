"""Opposition geometry — pure-layer unit tests (no DB, no network).

Locks the classification of opposition structure into one of four geometric
forms and the deterministic coordinate computation, including the
connection-first defaults (spectrum bias, willow not red/blue).
"""

from __future__ import annotations

from buddle.ai.argument import (
    OppositionType,
    StanceDistribution,
    build_opposition_view,
    classify_opposition,
)


def _d(**kw) -> StanceDistribution:  # type: ignore[no-untyped-def]
    return StanceDistribution(**kw)


# ── classification ──────────────────────────────────────────────────────────


def test_empty_defaults_to_spectrum():
    assert classify_opposition(_d()) is OppositionType.SPECTRUM


def test_continuous_distribution_is_spectrum():
    # spread across all buckets, single axis → spectrum (the default).
    d = _d(strong_con=1, con=3, neutral=4, pro=3, strong_pro=1, axis_count=1)
    assert classify_opposition(d) is OppositionType.SPECTRUM


def test_polar_thin_middle_is_binary():
    d = _d(strong_con=2, con=3, neutral=0, pro=4, strong_pro=1, axis_count=1)
    assert classify_opposition(d) is OppositionType.BINARY


def test_three_axes_is_multipolar():
    d = _d(con=2, neutral=2, pro=2, strong_pro=2, axis_count=4)
    assert classify_opposition(d) is OppositionType.MULTIPOLAR


def test_balanced_with_heavy_rebuttal_is_tension():
    d = _d(con=4, pro=4, neutral=1, rebuttal_count=5, axis_count=1)
    assert classify_opposition(d) is OppositionType.TENSION


def test_multipolar_takes_priority_over_binary():
    # polar AND 3+ axes → multipolar wins (the debate genuinely branched).
    d = _d(strong_con=3, pro=3, strong_pro=1, neutral=0, axis_count=3)
    assert classify_opposition(d) is OppositionType.MULTIPOLAR


# ── geometry output ─────────────────────────────────────────────────────────


def test_spectrum_places_nodes_along_axis():
    d = _d(strong_con=1, con=2, neutral=3, pro=2, strong_pro=1)
    v = build_opposition_view(d)
    assert v.opposition_type is OppositionType.SPECTRUM
    # one node per non-empty bucket, all on the mid-line, ordered left→right.
    assert len(v.nodes) == 5
    xs = [n.x for n in v.nodes]
    assert xs == sorted(xs)
    assert all(abs(n.y - 0.5) < 1e-9 for n in v.nodes)


def test_binary_has_thesis_and_two_poles():
    d = _d(strong_con=2, con=2, neutral=0, pro=3, strong_pro=1)
    v = build_opposition_view(d)
    kinds = [n.kind for n in v.nodes]
    assert "thesis" in kinds
    assert kinds.count("pole") == 2
    # hinge edges connect poles to the central thesis (not a clash line).
    assert all(e.kind == "hinge" for e in v.edges)


def test_multipolar_is_radial_around_center():
    d = _d(con=2, neutral=2, pro=2, strong_pro=2, axis_count=4)
    v = build_opposition_view(d)
    center = next(n for n in v.nodes if n.kind == "thesis")
    assert abs(center.x - 0.5) < 1e-9 and abs(center.y - 0.5) < 1e-9
    # every spoke edge starts at the center.
    assert all(abs(e.x1 - 0.5) < 1e-9 and abs(e.y1 - 0.5) < 1e-9 for e in v.edges)


def test_tension_has_interlocked_poles_with_seeds():
    d = _d(con=4, pro=4, neutral=1, rebuttal_count=5)
    v = build_opposition_view(d)
    assert v.opposition_type is OppositionType.TENSION
    # two poles + two inset seed dots (each side carries the other).
    assert sum(1 for n in v.nodes if n.kind == "pole") == 2
    assert sum(1 for n in v.nodes if n.kind == "seed") == 2


def test_node_radius_scales_with_weight():
    # a heavier pole should render larger than a lighter one.
    d = _d(strong_con=1, con=1, neutral=0, pro=6, strong_pro=4)
    v = build_opposition_view(d)
    poles = [n for n in v.nodes if n.kind == "pole"]
    pro_pole = next(n for n in poles if n.stance == "pro")
    con_pole = next(n for n in poles if n.stance == "con")
    assert pro_pole.radius > con_pole.radius


def test_geometry_is_deterministic():
    d = _d(strong_con=2, con=3, neutral=1, pro=3, strong_pro=2, axis_count=1)
    a = build_opposition_view(d)
    b = build_opposition_view(d)
    assert [(n.x, n.y, n.radius) for n in a.nodes] == [(n.x, n.y, n.radius) for n in b.nodes]


def test_all_coordinates_in_unit_square():
    for d in (
        _d(strong_con=2, con=3, neutral=1, pro=3, strong_pro=2),
        _d(con=4, pro=4, rebuttal_count=5),
        _d(con=2, neutral=2, pro=2, strong_pro=2, axis_count=4),
        _d(strong_con=3, pro=4, neutral=0),
    ):
        v = build_opposition_view(d)
        for n in v.nodes:
            assert 0.0 <= n.x <= 1.0 and 0.0 <= n.y <= 1.0
            assert 0.0 <= n.radius <= 0.2
