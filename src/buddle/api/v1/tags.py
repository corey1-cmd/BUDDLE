"""Tag routes — /v1/tags (read-only catalog for interest selection).

The persona-create UI needs the set of valid interest tags *with their ids*,
because PersonaCreate accepts ``interest_tag_ids`` (UUIDs that must already
exist — the service rejects unknown ids with 422). There was no endpoint to
discover those ids, so the front end could only send tag *names*, which the
backend can't map. This router closes that gap.

Deliberately read-only: tags are a curated taxonomy (post ingestion creates
them via the mediator, not arbitrary user input), so exposing a public
"create tag" route would invite spam and taxonomy drift. Users pick from the
existing catalog; they don't mint new tags here.
"""

from __future__ import annotations

from fastapi import APIRouter, Query
from sqlalchemy import func, select

from buddle.api.deps import DB, CurrentUser
from buddle.db.models.tag import Tag
from buddle.schemas.persona import TagBrief

router = APIRouter(prefix="/tags", tags=["tags"])


@router.get("", response_model=list[TagBrief], summary="List/search interest tags")
async def list_tags(
    user: CurrentUser,
    db: DB,
    q: str | None = Query(
        default=None, max_length=64, description="Case-insensitive name prefix/substring filter"
    ),
    limit: int = Query(default=50, ge=1, le=200),
) -> list[Tag]:
    """Return interest tags, optionally filtered by a substring of the name.

    Ordered by name for stable, predictable autocomplete. Auth-gated so the
    taxonomy isn't enumerable by anonymous clients (low-sensitivity, but the
    rest of the API requires a session and there's no reason to differ here).
    """
    stmt = select(Tag)
    if q:
        # Case-insensitive substring match. ILIKE with escaped wildcards so a
        # user-supplied % or _ can't turn into an injection of match semantics.
        escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        stmt = stmt.where(Tag.name.ilike(f"%{escaped}%", escape="\\"))
    stmt = stmt.order_by(func.lower(Tag.name)).limit(limit)
    result = await db.execute(stmt)
    return list(result.scalars().all())
