"""Pure importance-function property tests (no DB).

These lock in the mathematical guarantees the design depends on: additive
accumulation that's bounded by tanh, monotonicity, saturation, and the
midpoint transforms used for distribution/feed weighting.
"""

from __future__ import annotations

import pytest

from buddle.ai.importance import (
    ImportanceParams,
    distribution_multiplier,
    feed_score,
    normalize,
)

P = ImportanceParams(i_max=1.0, kappa=50.0)


def test_normalize_zero_is_zero():
    assert normalize(0.0, P) == 0.0


def test_normalize_sign_matches_raw():
    assert normalize(10.0, P) > 0
    assert normalize(-10.0, P) < 0


def test_normalize_bounded_by_i_max():
    # Even huge raw stays within (−i_max, i_max]; float tanh saturates at 1.0
    assert normalize(1e6, P) <= P.i_max
    assert normalize(-1e6, P) >= -P.i_max
    assert abs(normalize(123.0, P)) < P.i_max


def test_normalize_monotonic_increasing():
    import itertools

    xs = [-200, -50, -10, 0, 10, 50, 200]
    ys = [normalize(x, P) for x in xs]
    assert all(b > a for a, b in itertools.pairwise(ys))


def test_normalize_diminishing_returns():
    # Equal raw increments produce smaller normalized gains as |raw| grows.
    step = 10.0
    gain_near_zero = normalize(step, P) - normalize(0.0, P)
    gain_far = normalize(100 + step, P) - normalize(100.0, P)
    assert gain_far < gain_near_zero


def test_normalize_kappa_scales_saturation():
    slow = ImportanceParams(i_max=1.0, kappa=100.0)
    fast = ImportanceParams(i_max=1.0, kappa=10.0)
    # At the same raw, the smaller-kappa curve is closer to the ceiling.
    assert normalize(30.0, fast) > normalize(30.0, slow)


def test_distribution_multiplier_endpoints():
    assert distribution_multiplier(-1.0, P) == pytest.approx(0.0)
    assert distribution_multiplier(0.0, P) == pytest.approx(0.5)
    assert distribution_multiplier(1.0, P) == pytest.approx(1.0)


def test_distribution_multiplier_is_nonnegative_and_clamped():
    for n in [-2.0, -1.0, -0.3, 0.0, 0.7, 1.0, 2.0]:
        m = distribution_multiplier(n, P)
        assert 0.0 <= m <= 1.0


def test_feed_score_fresh_beats_stale_when_importance_equal():
    half_life = 24 * 3600
    fresh = feed_score(
        0.0,
        age_seconds=0,
        recency_half_life_seconds=half_life,
        w_importance=0.5,
        w_recency=0.5,
    )
    stale = feed_score(
        0.0,
        age_seconds=10 * half_life,
        recency_half_life_seconds=half_life,
        w_importance=0.5,
        w_recency=0.5,
    )
    assert fresh > stale


def test_feed_score_high_importance_beats_low_when_age_equal():
    half_life = 24 * 3600
    hi = feed_score(
        0.9,
        age_seconds=3600,
        recency_half_life_seconds=half_life,
        w_importance=0.5,
        w_recency=0.5,
    )
    lo = feed_score(
        -0.9,
        age_seconds=3600,
        recency_half_life_seconds=half_life,
        w_importance=0.5,
        w_recency=0.5,
    )
    assert hi > lo


def test_importance_params_validation():
    with pytest.raises(ValueError):
        ImportanceParams(i_max=0.0, kappa=50.0)
    with pytest.raises(ValueError):
        ImportanceParams(i_max=1.0, kappa=0.0)
