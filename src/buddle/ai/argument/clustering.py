"""Claim clustering — pure layer (deterministic k-means, no I/O, no LLM).

Groups claim embeddings into "conversation axes" (대화 축) — the distinct
threads a topic's debate has split into. This is the dashboard's core
organizing move: instead of an undifferentiated pile of posts, the user sees
"this topic has 3 main lines of argument, and here's where each leans."

Why a hand-rolled k-means rather than sklearn: determinism and zero heavy
deps. A fixed seed + fixed init (k-means++ style farthest-point seeding from a
deterministic start) means the same posts always yield the same axes, which is
required for the codebase's "auditable, reproducible" property and for stable
test assertions. Cosine distance matches the embedding space used everywhere
else (BGE-M3, normalized).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

_MAX_K = 5  # at most 5 conversation axes (dashboard readability)
_MAX_ITERS = 25
_MIN_POINTS_PER_EXTRA_K = 3  # need ~3 claims to justify another axis


@dataclass(frozen=True, slots=True)
class Cluster:
    """One conversation axis: the indices of claims assigned to it."""

    centroid: list[float]
    member_indices: list[int]


def _dot(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))


def _norm(a: list[float]) -> float:
    return math.sqrt(_dot(a, a))


def cosine_distance(a: list[float], b: list[float]) -> float:
    """1 - cosine similarity, in [0, 2]. Zero vectors are maximally distant."""
    na, nb = _norm(a), _norm(b)
    if na == 0.0 or nb == 0.0:
        return 1.0
    return 1.0 - _dot(a, b) / (na * nb)


def _mean(points: list[list[float]]) -> list[float]:
    n = len(points)
    dim = len(points[0])
    acc = [0.0] * dim
    for p in points:
        for i in range(dim):
            acc[i] += p[i]
    return [v / n for v in acc]


def choose_k(n_points: int) -> int:
    """How many axes to form: 1 axis per ~3 claims, capped at 5.

    Few claims → one axis (a topic just starting). The cap keeps the dashboard
    legible no matter how large the debate grows.
    """
    if n_points <= 1:
        return 1
    k = 1 + (n_points - 1) // _MIN_POINTS_PER_EXTRA_K
    return max(1, min(_MAX_K, k))


def _seed_indices(points: list[list[float]], k: int) -> list[int]:
    """Deterministic farthest-point seeding (k-means++ without randomness).

    Start from index 0, then repeatedly pick the point farthest (max cosine
    distance) from the nearest already-chosen seed. Fully reproducible.
    """
    seeds = [0]
    while len(seeds) < k:
        best_idx, best_dist = -1, -1.0
        for i in range(len(points)):
            if i in seeds:
                continue
            nearest = min(cosine_distance(points[i], points[s]) for s in seeds)
            if nearest > best_dist:
                best_dist, best_idx = nearest, i
        if best_idx < 0:
            break
        seeds.append(best_idx)
    return seeds


def cluster_claims(embeddings: list[list[float]], *, k: int | None = None) -> list[Cluster]:
    """Cluster claim embeddings into conversation axes (deterministic k-means).

    Returns clusters with non-empty membership, ordered largest-first (the
    dominant axes lead the dashboard). Empty input → no clusters.
    """
    n = len(embeddings)
    if n == 0:
        return []
    if n == 1:
        return [Cluster(centroid=list(embeddings[0]), member_indices=[0])]

    kk = k if k is not None else choose_k(n)
    kk = max(1, min(kk, n))

    seeds = _seed_indices(embeddings, kk)
    centroids = [list(embeddings[s]) for s in seeds]

    assignments = [0] * n
    for _ in range(_MAX_ITERS):
        changed = False
        for i in range(n):
            best_c, best_d = 0, math.inf
            for c in range(len(centroids)):
                d = cosine_distance(embeddings[i], centroids[c])
                if d < best_d:
                    best_d, best_c = d, c
            if assignments[i] != best_c:
                assignments[i] = best_c
                changed = True
        # Recompute centroids from current membership.
        new_centroids: list[list[float]] = []
        for c in range(len(centroids)):
            members = [embeddings[i] for i in range(n) if assignments[i] == c]
            new_centroids.append(_mean(members) if members else centroids[c])
        centroids = new_centroids
        if not changed:
            break

    clusters: list[Cluster] = []
    for c in range(len(centroids)):
        member_idx = [i for i in range(n) if assignments[i] == c]
        if member_idx:
            clusters.append(Cluster(centroid=centroids[c], member_indices=member_idx))

    clusters.sort(key=lambda cl: len(cl.member_indices), reverse=True)
    return clusters


def representative_index(cluster: Cluster, embeddings: list[list[float]]) -> int:
    """The claim closest to the cluster centroid — the axis's representative."""
    best_idx, best_d = cluster.member_indices[0], math.inf
    for i in cluster.member_indices:
        d = cosine_distance(embeddings[i], cluster.centroid)
        if d < best_d:
            best_d, best_idx = d, i
    return best_idx
