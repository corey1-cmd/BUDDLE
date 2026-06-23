"""Plaza cadence — pure rules for read-detection and AI comment/post frequency.

These encode the spec's intent:
  - A post is "read" only after a dwell time proportional to its LENGTH (a
    scroll-past doesn't count). The client signals a read after that dwell;
    the server validates the minimum interval to resist abuse.
  - The number of AI comments grows with how many times a post was genuinely
    read (not with raw views).
  - Virtual personas post on a periodic cadence.

Pure functions, no I/O — easy to test and tune.
"""

from __future__ import annotations

# Reading speed assumptions. Korean prose ~ 500 chars/min ≈ 120 ms/char; we add
# a floor so very short posts still need a real glance.
_MS_PER_CHAR = 120.0
_MIN_READ_MS = 1500.0  # at least 1.5s of dwell counts as a read
_MAX_READ_MS = 60_000.0  # cap so huge posts don't demand unrealistic dwell


def expected_read_ms(content_length: int) -> float:
    """Dwell time (ms) that should elapse before a post counts as read."""
    raw = _MIN_READ_MS + _MS_PER_CHAR * max(content_length, 0)
    return min(raw, _MAX_READ_MS)


def is_genuine_read(content_length: int, dwell_ms: float) -> bool:
    """Whether a reported dwell qualifies as a genuine read for this length."""
    return dwell_ms >= expected_read_ms(content_length)


# How many genuine reads are needed per AI comment, and the hard cap of AI
# comments per post (guardrail so popular posts don't get spammed).
READS_PER_COMMENT = 3
MAX_AI_COMMENTS_PER_POST = 8


def target_ai_comment_count(read_count: int) -> int:
    """How many AI comments a post with this read_count should have."""
    if read_count <= 0:
        return 0
    return min(read_count // READS_PER_COMMENT, MAX_AI_COMMENTS_PER_POST)


def comments_to_add(read_count: int, existing_ai_comments: int) -> int:
    """How many NEW AI comments to add now (>=0), given current state."""
    target = target_ai_comment_count(read_count)
    return max(target - existing_ai_comments, 0)


# Virtual-persona posting cadence: minimum minutes between a given virtual
# persona's posts, so one persona doesn't flood the board.
MIN_MINUTES_BETWEEN_VIRTUAL_POSTS = 30


def virtual_persona_may_post(minutes_since_last_post: float | None) -> bool:
    """Whether a virtual persona is due to post again."""
    if minutes_since_last_post is None:
        return True  # never posted
    return minutes_since_last_post >= MIN_MINUTES_BETWEEN_VIRTUAL_POSTS
