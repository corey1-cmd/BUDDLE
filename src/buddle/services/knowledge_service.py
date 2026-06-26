"""Knowledge service — wires the pure core to embeddings + DB (Layer B).

Entry points:
  consider_post   write path: extract 1..5 units, score each via the selection
                  gate, store only those worth retaining (rest let pass).
  update_topic_edges  grow the topic association graph from a post's tags +
                  unit embeddings.
  build_pools     refresh per-topic ConversationPools (reference material).
  fetch_context   read path: serve a persona reference material for a topic
                  (plus one-hop related topics) in their language; records use.

Privacy: only PUBLIC units are ever served cross-persona. A persona may see its
OWN private units. Recombination/serving never crosses the private boundary.

All recombination/synthesis (InsightBundle) is intentionally OUT of scope here
(deferred). This stage produces only curated reference data.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from buddle.ai.embeddings import get_embedding_provider
from buddle.ai.knowledge import (
    RawUnit,
    SelectionSignals,
    SelectionWeights,
    edge_delta,
    extract_units,
    normalize_pair,
    novelty_from_similarity,
    redundancy_from_count,
    should_retain,
)
from buddle.ai.plaza.cadence import is_genuine_read
from buddle.core.logging import get_logger
from buddle.db.models.conversation_pool import ConversationPool, PoolUnit
from buddle.db.models.enums import PostVisibility
from buddle.db.models.importance import ImportanceScore
from buddle.db.models.knowledge_audit import KnowledgeAudit
from buddle.db.models.knowledge_unit import KnowledgeUnit
from buddle.db.models.persona_context_ref import PersonaContextRef
from buddle.db.models.post import Post
from buddle.db.models.topic_edge import TopicEdge

log = get_logger(__name__)

# Tunables (config-overridable later; mirror design doc defaults).
NOVELTY_WINDOW = 50  # how many recent units to compare for novelty
REDUNDANCY_SIM = 0.92  # cosine >= this counts a near-duplicate
EDGE_PROX_MIN = 0.5  # only link topics whose units are at least this close
POOL_SERVE_LIMIT = 8  # max units returned per fetch
EDGE_HOP_LIMIT = 1  # related-topic hops in fetch_context


@dataclass(frozen=True, slots=True)
class ConsiderResult:
    retained: int
    skipped: int
    unit_ids: list[uuid.UUID]


@dataclass(frozen=True, slots=True)
class ContextItem:
    unit_id: uuid.UUID
    gist: str
    topic_tags: str
    language: str


@dataclass(frozen=True, slots=True)
class ContextBundle:
    topic: str
    items: list[ContextItem]
    related_topics: list[str]


def _tags_list(raw: str) -> list[str]:
    return [t.strip() for t in raw.split(",") if t.strip()]


async def _recent_embeddings(db: AsyncSession, *, limit: int = NOVELTY_WINDOW) -> list[list[float]]:
    rows = (
        await db.execute(
            select(KnowledgeUnit.embedding)
            .where(KnowledgeUnit.embedding.is_not(None))
            .order_by(KnowledgeUnit.created_at.desc())
            .limit(limit)
        )
    ).scalars()
    return [list(e) for e in rows if e is not None]


def _max_cosine_sim(vec: list[float], others: list[list[float]]) -> float:
    """Highest cosine similarity between vec and any of others ([-1,1])."""
    if not others:
        return 0.0
    import math

    def dot(a: list[float], b: list[float]) -> float:
        return sum(x * y for x, y in zip(a, b, strict=False))

    nv = math.sqrt(dot(vec, vec)) or 1.0
    best = -1.0
    for o in others:
        no = math.sqrt(dot(o, o)) or 1.0
        sim = dot(vec, o) / (nv * no)
        best = max(best, sim)
    return best


def _sim_stats(
    vec: list[float], others: list[list[float]], *, dup_threshold: float
) -> tuple[float, int, float]:
    """Single-pass max-similarity, near-duplicate count, AND mean similarity.

    Vectorized with numpy: builds an (N, d) matrix and computes all cosine
    similarities at once, instead of a Python double loop. max + count are
    mathematically identical to the previous per-element cosine; mean is the
    average positive cohesion used for topic_fit. Empty input -> (0.0, 0, 0.0);
    zero norms -> treated as 1.0, exactly as before.
    """
    if not others:
        return 0.0, 0, 0.0
    import numpy as np

    v = np.asarray(vec, dtype=np.float64)
    m = np.asarray(others, dtype=np.float64)
    nv = float(np.sqrt(v @ v)) or 1.0
    row_norms = np.sqrt((m * m).sum(axis=1))
    row_norms[row_norms == 0.0] = 1.0
    sims = (m @ v) / (row_norms * nv)
    best = float(sims.max())
    dupes = int((sims >= dup_threshold).sum())
    # Mean of positive similarities = cohesion with existing context (topic_fit).
    positive = sims[sims > 0.0]
    mean_pos = float(positive.mean()) if positive.size else 0.0
    return best, dupes, mean_pos


async def consider_post(
    db: AsyncSession,
    post_id: uuid.UUID,
    *,
    weights: SelectionWeights | None = None,
    commit: bool = True,
) -> ConsiderResult:
    """Write path: extract units, run the selection gate, store the keepers.

    Reads the post + its importance; does NOT mutate post state (separate from
    the publish transaction). Best-effort: caller wraps in suppress().
    """
    post = await db.get(Post, post_id)
    if post is None:
        return ConsiderResult(0, 0, [])

    importance = (
        await db.scalar(
            select(ImportanceScore.normalized).where(ImportanceScore.post_id == post_id)
        )
        or 0.0
    )
    genuine = is_genuine_read(len(post.content_transformed), float(post.read_count) * 1000.0)
    # Tag the units with the mediator's PostTags so they are retrievable by topic
    # (fetch_context filters on topic_tags). Without this the knowledge space is
    # write-only — units exist but no topic query can ever find them.
    from buddle.db.models.tag import PostTag, Tag

    post_tags = list(
        (
            await db.execute(
                select(Tag.name)
                .join(PostTag, PostTag.tag_id == Tag.id)
                .where(PostTag.post_id == post_id)
            )
        ).scalars()
    )
    topic_tags_str = ",".join(dict.fromkeys(t for t in post_tags if t))

    units: list[RawUnit] = extract_units(post.content_transformed)
    if not units:
        return ConsiderResult(0, 0, [])

    embedder = get_embedding_provider()
    recent = await _recent_embeddings(db)

    retained = 0
    skipped = 0
    new_ids: list[uuid.UUID] = []
    for u in units:
        emb = await embedder.embed_one(u.gist)
        max_sim, near_dupes, mean_sim = _sim_stats(emb, recent, dup_threshold=REDUNDANCY_SIM)
        novelty = novelty_from_similarity(max_sim)
        redundancy = redundancy_from_count(near_dupes)
        signals = SelectionSignals(
            genuine_read=genuine,
            importance=float(importance),
            novelty=novelty,
            # topic_fit = average positive cohesion with existing units. On cold
            # start (no prior context) the unit defines the space it joins, so it
            # fits perfectly (1.0). With the neutral 0.5 fallback a maximally
            # novel first unit scored novelty(0.30)+fit(0.075)=0.375 < 0.45 and
            # was always dropped, so the knowledge space could never seed from
            # writing alone (only from reads/likes). 1.0 lets first content seed.
            topic_fit=mean_sim if recent else 1.0,
            redundancy=redundancy,
        )
        if not should_retain(signals, weights):
            skipped += 1
            continue

        # Trigger gate (leukocyte): re-screen the unit's gist before storing.
        # Recombination can surface new context, so even already-published text
        # is re-checked. Blocked -> let pass (skip), audit the block.
        screen = await _screen_unit(db, u.gist)
        if not screen:
            skipped += 1
            continue

        from buddle.ai.knowledge import retention_score as _score

        unit = KnowledgeUnit(
            source_post_id=post_id,
            persona_id=post.source_persona_id,
            gist=u.gist,
            language=post.source_language,
            topic_tags=topic_tags_str,
            embedding=emb,
            visibility=post.visibility.value
            if isinstance(post.visibility, PostVisibility)
            else str(post.visibility),
            retention_score=_score(signals, weights),
            integrity_sig=_sign_unit(u.gist),
        )
        db.add(unit)
        retained += 1
        recent.insert(0, emb)  # so later units in same post see this one
        new_ids.append(unit.id)

    if commit and retained:
        await db.commit()
    log.info("knowledge.consider", post_id=str(post_id), retained=retained, skipped=skipped)
    return ConsiderResult(retained=retained, skipped=skipped, unit_ids=new_ids)


async def update_topic_edges(db: AsyncSession, topics: list[str], *, commit: bool = True) -> int:
    """Strengthen edges among a set of co-occurring topics. Returns edges touched."""
    uniq = sorted({t.strip() for t in topics if t.strip()})
    touched = 0
    for i in range(len(uniq)):
        for j in range(i + 1, len(uniq)):
            a, b = normalize_pair(uniq[i], uniq[j])
            edge = (
                await db.execute(
                    select(TopicEdge).where(TopicEdge.topic_a == a, TopicEdge.topic_b == b)
                )
            ).scalar_one_or_none()
            delta = edge_delta(co_occurred=True, emb_proximity=0.0)
            if edge is None:
                db.add(TopicEdge(topic_a=a, topic_b=b, weight=delta))
            else:
                edge.weight = max(0.0, edge.weight + delta)
            touched += 1
    if commit and touched:
        await db.commit()
    return touched


async def _related_topics(db: AsyncSession, topic: str, *, hops: int = EDGE_HOP_LIMIT) -> list[str]:
    if hops <= 0:
        return []
    rows = (
        await db.execute(
            select(TopicEdge)
            .where((TopicEdge.topic_a == topic) | (TopicEdge.topic_b == topic))
            .order_by(TopicEdge.weight.desc())
            .limit(5)
        )
    ).scalars()
    related: list[str] = []
    for e in rows:
        other = e.topic_b if e.topic_a == topic else e.topic_a
        if other != topic and other not in related:
            related.append(other)
    return related


def _whole_tag_clause(topic: str):  # type: ignore[no-untyped-def]
    """Match `topic` as a WHOLE comma-delimited tag, not a substring.

    topic_tags is stored as "tag1,tag2,tag3"; we wrap it in commas and look for
    ",topic," so 'AI' matches the 'AI' tag but never 'AIDS' (which the old
    `LIKE '%AI%'` falsely matched). LIKE wildcards in the topic are escaped.
    """
    from sqlalchemy import literal

    esc = topic.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    wrapped = literal(",") + KnowledgeUnit.topic_tags + literal(",")
    return wrapped.like(f"%,{esc},%", escape="\\")


async def fetch_context(
    db: AsyncSession,
    persona_id: uuid.UUID,
    *,
    topic: str,
    requesting_persona_id: uuid.UUID | None = None,
    limit: int = POOL_SERVE_LIMIT,
    include_insights: bool = False,
    record_ref: bool = True,
) -> ContextBundle:
    """Read path: serve reference units for `topic` (+ related topics).

    Privacy: PUBLIC units always; PRIVATE units only if owned by the requesting
    persona. When `record_ref` is True (default) a PersonaContextRef for the
    served pool is written + committed; pass False for a PURE read (e.g. the
    dialogue hot path, which must not write on every turn).
    """
    requester = requesting_persona_id or persona_id
    related = await _related_topics(db, topic)
    topics = [topic, *related]

    # Units tagged with any of these topics (whole-tag match), honoring visibility.
    from sqlalchemy import or_

    clauses = [_whole_tag_clause(t) for t in topics]
    q = select(KnowledgeUnit).where(or_(*clauses)) if clauses else select(KnowledgeUnit)
    q = (
        q.where(
            (KnowledgeUnit.visibility == PostVisibility.PUBLIC.value)
            | (KnowledgeUnit.persona_id == requester)
        )
        .order_by(KnowledgeUnit.retention_score.desc())
        .limit(max(1, min(limit, 50)))
    )

    rows = list((await db.execute(q)).scalars())
    items = [
        ContextItem(unit_id=u.id, gist=u.gist, topic_tags=u.topic_tags, language=u.language)
        for u in rows
    ]

    # Optionally include an approved integration insight for this topic.
    if include_insights:
        from buddle.db.models.insight_bundle import InsightBundle

        bundle = (
            await db.execute(
                select(InsightBundle)
                .where(
                    InsightBundle.topic == topic,
                    InsightBundle.status == "approved",
                    InsightBundle.visibility == PostVisibility.PUBLIC.value,
                )
                .order_by(InsightBundle.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if bundle is not None:
            items.insert(
                0,
                ContextItem(
                    unit_id=bundle.id,
                    gist=f"[통합 인사이트] {bundle.summary}",
                    topic_tags=topic,
                    language=bundle.language,
                ),
            )

    # Record reference to the topic's pool, if one exists (write path — opt-out
    # via record_ref=False to keep the read pure).
    if record_ref:
        pool = (
            await db.execute(
                select(ConversationPool).where(ConversationPool.topic == topic).limit(1)
            )
        ).scalar_one_or_none()
        if pool is not None:
            db.add(
                PersonaContextRef(
                    persona_id=requester, pool_id=pool.id, relevance=float(len(items))
                )
            )
            await db.commit()

    return ContextBundle(topic=topic, items=items, related_topics=related)


async def build_pool(db: AsyncSession, topic: str, *, commit: bool = True) -> uuid.UUID | None:
    """Refresh (or create) the ConversationPool for a topic from its units."""
    units = list(
        (
            await db.execute(
                select(KnowledgeUnit.id).where(KnowledgeUnit.topic_tags.like(f"%{topic}%"))
            )
        ).scalars()
    )
    if not units:
        return None
    pool = (
        await db.execute(select(ConversationPool).where(ConversationPool.topic == topic).limit(1))
    ).scalar_one_or_none()
    if pool is None:
        pool = ConversationPool(topic=topic, size=len(units), freshness=1.0)
        db.add(pool)
        await db.flush()
    else:
        pool.size = len(units)
        pool.freshness = 1.0
    # reset membership
    existing = list(
        (await db.execute(select(PoolUnit).where(PoolUnit.pool_id == pool.id))).scalars()
    )
    for pu in existing:
        await db.delete(pu)
    for uid in units:
        db.add(PoolUnit(pool_id=pool.id, unit_id=uid, membership_score=1.0))
    if commit:
        await db.commit()
    return pool.id


# ── Supervising AI triggers + standby (Layer B §4) ─────────────────────────


async def _screen_unit(db: AsyncSession, gist: str) -> bool:
    """Leukocyte trigger: True = safe to store, False = block (let pass).

    Reuses the response-side ethics gate; fail-open on backend error.
    """
    from buddle.services import leukocyte_service

    try:
        result = await leukocyte_service.screen_response(gist)
    except Exception:
        return True  # fail-open: don't block normal content on backend error
    if not result.allowed:
        db.add(
            KnowledgeAudit(
                actor_ai="leukocyte",
                action="block_unit",
                target_type="unit",
                target_id=None,
                verdict="blocked",
                note="recombination ethics re-screen",
            )
        )
    return result.allowed


def _sign_unit(gist: str) -> str:
    """Technician trigger: HMAC-SHA256 integrity signature over the gist."""
    import hashlib
    import hmac

    from buddle.config import get_settings

    key = get_settings().integrity_hmac_key.get_secret_value().encode("utf-8")
    return hmac.new(key, gist.encode("utf-8"), hashlib.sha256).hexdigest()[:128]


async def knowledge_tick(db: AsyncSession) -> dict[str, int]:
    """Standby pass for the three supervising AIs (called by an external cron,
    same pattern as plaza tick). One bounded sweep:

      central:    measure retention rate + emit a health note (autotune hook)
      technician: verify integrity signatures on a recent sample
      leukocyte:  re-screen a recent sample of stored units
      edges:      apply one decay step to topic edges

    Returns counters. DB-backed; runs under Docker/CI.
    """
    from buddle.ai.knowledge import DECAY

    counters = {"checked": 0, "edges_decayed": 0, "integrity_ok": 0, "rescreen_ok": 0}

    # technician + leukocyte: sample recent units
    recent = list(
        (
            await db.execute(
                select(KnowledgeUnit).order_by(KnowledgeUnit.created_at.desc()).limit(20)
            )
        ).scalars()
    )
    for u in recent:
        counters["checked"] += 1
        if u.integrity_sig and u.integrity_sig == _sign_unit(u.gist):
            counters["integrity_ok"] += 1
        try:
            from buddle.services import leukocyte_service

            res = await leukocyte_service.screen_response(u.gist)
            if res.allowed:
                counters["rescreen_ok"] += 1
        except Exception:
            counters["rescreen_ok"] += 1  # fail-open

    # pools + edges: organize recent units into per-topic ConversationPools (the
    # 'conversation pool' sub-layer the dialogue read path serves from) and grow
    # the topic-association graph. Without this the space stays as loose units
    # and the pool layer never forms.
    counters["pools_built"] = 0
    topic_set: set[str] = set()
    for u in recent:
        unit_topics = _tags_list(u.topic_tags)
        if unit_topics:
            await update_topic_edges(db, unit_topics, commit=False)
            topic_set.update(unit_topics)
    for topic in list(topic_set)[:20]:
        if await build_pool(db, topic, commit=False) is not None:
            counters["pools_built"] += 1

    # edges: one decay step
    edges = list((await db.execute(select(TopicEdge))).scalars())
    for e in edges:
        e.weight = e.weight * DECAY
        counters["edges_decayed"] += 1

    # central: select pools worth integrating (large + fresh, no recent bundle)
    # and synthesize them — selective standby integration.
    from buddle.ai.knowledge import BUNDLE_MIN_UNITS, FRESHNESS_FLOOR
    from buddle.db.models.conversation_pool import ConversationPool

    counters["bundles"] = 0
    pools = list(
        (
            await db.execute(
                select(ConversationPool)
                .where(
                    ConversationPool.size >= BUNDLE_MIN_UNITS,
                    ConversationPool.freshness >= FRESHNESS_FLOOR,
                )
                .order_by(ConversationPool.freshness.desc())
                .limit(3)
            )
        ).scalars()
    )
    for pool in pools:
        # Skip pools that already have a recent approved bundle (avoid dup
        # synthesis piling up). One bundle per pool until it changes materially.
        from buddle.db.models.insight_bundle import InsightBundle

        existing = (
            await db.execute(
                select(InsightBundle.id)
                .where(
                    InsightBundle.pool_id == pool.id,
                    InsightBundle.status == "approved",
                )
                .limit(1)
            )
        ).scalar_one_or_none()
        if existing is not None:
            continue
        bundle_id = await synthesize_bundle(db, pool.id, commit=False)
        if bundle_id is not None:
            counters["bundles"] += 1

    # central: health note (retention rate proxy via stored count)
    db.add(
        KnowledgeAudit(
            actor_ai="central",
            action="standby_tick",
            target_type="space",
            target_id=None,
            verdict="ok",
            note=f"checked={counters['checked']} edges={counters['edges_decayed']}",
        )
    )
    await db.commit()
    log.info("knowledge.tick", **counters)
    return counters


# ── Integration / synthesis (Layer B, selective) ───────────────────────────


async def synthesize_bundle(
    db: AsyncSession, pool_id: uuid.UUID, *, commit: bool = True
) -> uuid.UUID | None:
    """Selectively integrate a pool's units into an InsightBundle.

    Only runs when the pool is large + fresh enough (should_synthesize). All
    input units must share visibility (public-only for a public bundle) so the
    private boundary is never crossed. The summary is ethics-screened
    (leukocyte) and integrity-signed (technician). Returns the bundle id, or
    None if synthesis was skipped/blocked.
    """
    from buddle.ai.knowledge import (
        UnitView,
        get_synthesizer,
        plan_synthesis,
        should_synthesize,
    )
    from buddle.db.models.conversation_pool import ConversationPool
    from buddle.db.models.insight_bundle import InsightBundle

    pool = await db.get(ConversationPool, pool_id)
    if pool is None:
        return None

    # Gather member units.
    unit_ids = list(
        (await db.execute(select(PoolUnit.unit_id).where(PoolUnit.pool_id == pool_id))).scalars()
    )
    if not unit_ids:
        return None
    units = list(
        (await db.execute(select(KnowledgeUnit).where(KnowledgeUnit.id.in_(unit_ids)))).scalars()
    )

    # Visibility homogeneity: prefer public-only set (private never merged into
    # a servable bundle here). If a public subset exists, use it; else skip.
    public_units = [u for u in units if str(u.visibility) == PostVisibility.PUBLIC.value]
    chosen = public_units
    if not should_synthesize(len(chosen), float(pool.freshness)):
        return None

    views = [
        UnitView(
            unit_id=str(u.id),
            gist=u.gist,
            tags=tuple(_tags_list(u.topic_tags)),
        )
        for u in chosen
    ]
    emb_by_id = {str(u.id): (list(u.embedding) if u.embedding is not None else []) for u in chosen}

    def _sim(a: str, b: str) -> float:
        va, vb = emb_by_id.get(a, []), emb_by_id.get(b, [])
        if not va or not vb:
            return 0.0
        return _max_cosine_sim(va, [vb])

    plan = plan_synthesis(views, _sim)
    language = chosen[0].language if chosen else "ko"

    try:
        summary, reasoning = await get_synthesizer().synthesize(
            topic=pool.topic, units=views, plan=plan, language=language
        )
    except Exception:
        log.warning("knowledge.synthesize_error", pool_id=str(pool_id))
        return None

    # Trigger gates: leukocyte ethics re-check + technician signature.
    status = "approved"
    allowed = await _screen_unit(db, summary)
    if not allowed:
        status = "blocked"

    bundle = InsightBundle(
        pool_id=pool_id,
        topic=pool.topic,
        summary=summary,
        reasoning_trace=reasoning,
        contributing_unit_ids=",".join(plan.contributing_ids),
        language=language,
        visibility=PostVisibility.PUBLIC.value,
        status=status,
        integrity_sig=_sign_unit(summary),
    )
    db.add(bundle)
    db.add(
        KnowledgeAudit(
            actor_ai="central",
            action="synthesize_bundle",
            target_type="bundle",
            target_id=None,
            verdict=status,
            note=f"topic={pool.topic} units={len(chosen)}",
        )
    )
    if commit:
        await db.commit()
    return bundle.id if status == "approved" else None
