"""Plaza AI helpers — cadence rules + virtual persona role definitions (pure)."""

from buddle.ai.plaza.cadence import (
    MAX_AI_COMMENTS_PER_POST,
    MIN_MINUTES_BETWEEN_VIRTUAL_POSTS,
    READS_PER_COMMENT,
    comments_to_add,
    expected_read_ms,
    is_genuine_read,
    target_ai_comment_count,
    virtual_persona_may_post,
)
from buddle.ai.plaza.virtual_roles import (
    RoleProfile,
    all_roles,
    build_post_prompt,
    get_profile,
)

__all__ = [
    "MAX_AI_COMMENTS_PER_POST",
    "MIN_MINUTES_BETWEEN_VIRTUAL_POSTS",
    "READS_PER_COMMENT",
    "RoleProfile",
    "all_roles",
    "build_post_prompt",
    "comments_to_add",
    "expected_read_ms",
    "get_profile",
    "is_genuine_read",
    "target_ai_comment_count",
    "virtual_persona_may_post",
]
