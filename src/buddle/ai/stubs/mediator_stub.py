"""Stage 1 stub: rule-based mediator AI.

- Tagging: extracts up to 5 most frequent content words (length >= 2) from text.
- Distribution: matches by tag overlap with persona_interest_tags.
- Re-form: passes through content_transformed (no actual restructuring).

Replaced by an LLM/embedding-backed implementation in Stage 2+.
"""

from __future__ import annotations

import re
import uuid
from collections import Counter

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from buddle.ai.interfaces import DistributionTarget, MediatorTagging
from buddle.db.models.persona import Persona
from buddle.db.models.tag import PersonaInterestTag, Tag

_TOKEN_RE = re.compile(r"[A-Za-z가-힣]{2,}")
_STOPWORDS = frozenset(
    {
        # Korean
        "그리고",
        "그러나",
        "하지만",
        "그래서",
        "이것",
        "저것",
        "그것",
        "여기",
        "저기",
        "거기",
        "정말",
        "진짜",
        "조금",
        "많이",
        "너무",
        "오늘",
        "내일",
        "어제",
        "지금",
        "나는",
        "너는",
        "우리",
        # English
        "the",
        "and",
        "for",
        "with",
        "that",
        "this",
        "from",
        "have",
        "you",
        "are",
        "but",
        "not",
        "all",
        "can",
        "was",
        "were",
    }
)


def _extract_keywords(text: str, top_k: int = 5) -> list[str]:
    """Extract top-K content words by frequency, excluding stopwords."""
    tokens = [t.lower() for t in _TOKEN_RE.findall(text)]
    tokens = [t for t in tokens if t not in _STOPWORDS and len(t) >= 2]
    if not tokens:
        return []
    counter = Counter(tokens)
    return [w for w, _ in counter.most_common(top_k)]


class MediatorStub:
    """Rule-based mediator: keyword tagging + tag-overlap distribution."""

    def __init__(self, db: AsyncSession):
        self._db = db

    async def tag_and_restructure(
        self,
        *,
        content_transformed: str,
        existing_tags: list[str],
    ) -> MediatorTagging:
        derived = _extract_keywords(content_transformed)
        # Merge with any existing tag suggestions, dedupe preserving order
        seen: set[str] = set()
        merged: list[str] = []
        for t in [*existing_tags, *derived]:
            tl = t.lower()
            if tl not in seen:
                seen.add(tl)
                merged.append(tl)
        return MediatorTagging(tag_names=merged[:8], summary=content_transformed)

    async def select_distribution_targets(
        self,
        *,
        source_persona_id: uuid.UUID,
        content_transformed: str,
        tag_names: list[str],
        max_targets: int = 5,
    ) -> list[DistributionTarget]:
        """Pick personas whose interest_tags overlap the post's tags.

        Relevance is a simple overlap count, normalized to [0, 1].
        Source persona is excluded so users don't receive their own posts.
        """
        if not tag_names:
            return []

        # Find tag IDs for the given names
        tag_rows = await self._db.execute(select(Tag.id, Tag.name).where(Tag.name.in_(tag_names)))
        tag_id_map = {row[1]: row[0] for row in tag_rows.all()}
        if not tag_id_map:
            return []

        # Group personas by how many of those tag IDs they're interested in
        stmt = (
            select(
                Persona.id,
                func.count(PersonaInterestTag.tag_id).label("overlap"),
            )
            .join(
                PersonaInterestTag,
                PersonaInterestTag.persona_id == Persona.id,
            )
            .where(
                PersonaInterestTag.tag_id.in_(tag_id_map.values()),
                Persona.id != source_persona_id,
                Persona.is_active.is_(True),
            )
            .group_by(Persona.id)
            .order_by(func.count(PersonaInterestTag.tag_id).desc())
            .limit(max_targets)
        )
        result = await self._db.execute(stmt)
        rows = result.all()

        max_overlap = max((int(r[1]) for r in rows), default=1)
        return [
            DistributionTarget(
                target_persona_id=row[0],
                relevance_score=round(int(row[1]) / max_overlap, 4),
            )
            for row in rows
        ]
