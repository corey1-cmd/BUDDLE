"""Plaza virtual-persona + cadence tests — pure, no DB.

Covers the read-detection rule, read-to-comment proportionality with its cap,
the virtual-posting interval, and the role->prompt builder. DB-backed flows
(tick publishing, comment triggering) run in CI.
"""

from __future__ import annotations

from buddle.ai.plaza import (
    MAX_AI_COMMENTS_PER_POST,
    build_post_prompt,
    comments_to_add,
    expected_read_ms,
    is_genuine_read,
    target_ai_comment_count,
    virtual_persona_may_post,
)
from buddle.ai.plaza.cadence import READS_PER_COMMENT
from buddle.db.models.enums import VirtualRole

# ── read detection (length-proportional dwell) ───────────────────────────


def test_expected_read_time_grows_with_length():
    assert expected_read_ms(0) < expected_read_ms(100) < expected_read_ms(1000)


def test_expected_read_time_has_floor():
    # even an empty post needs a minimum dwell
    assert expected_read_ms(0) >= 1500


def test_expected_read_time_capped():
    # extremely long post doesn't demand more than the cap
    assert expected_read_ms(10_000) <= 60_000


def test_genuine_read_requires_enough_dwell():
    # 100 chars => 1500 + 120*100 = 13500 ms
    assert not is_genuine_read(100, 1000)  # scroll-past
    assert is_genuine_read(100, 14000)  # real read


def test_scroll_past_never_counts():
    # very short dwell on any length fails
    for length in [10, 100, 1000]:
        assert not is_genuine_read(length, 200)


# ── read -> comment proportionality ──────────────────────────────────────


def test_no_comments_below_threshold():
    assert target_ai_comment_count(READS_PER_COMMENT - 1) == 0


def test_comments_scale_with_reads():
    assert target_ai_comment_count(READS_PER_COMMENT) == 1
    assert target_ai_comment_count(READS_PER_COMMENT * 3) == 3


def test_comment_count_is_capped():
    assert target_ai_comment_count(10_000) == MAX_AI_COMMENTS_PER_POST


def test_comments_to_add_accounts_for_existing():
    # 9 reads -> target 3; already 1 -> add 2
    assert comments_to_add(9, 1) == 2
    # already at/over target -> add 0
    assert comments_to_add(9, 3) == 0
    assert comments_to_add(9, 5) == 0


def test_comments_to_add_never_negative():
    assert comments_to_add(0, 0) == 0
    assert comments_to_add(3, 10) == 0


# ── virtual posting cadence ──────────────────────────────────────────────


def test_virtual_persona_posts_if_never_posted():
    assert virtual_persona_may_post(None)


def test_virtual_persona_waits_for_interval():
    assert not virtual_persona_may_post(5.0)  # 5 min < 30 min
    assert virtual_persona_may_post(31.0)


# ── role prompt builder ──────────────────────────────────────────────────


def test_build_prompt_includes_briefing_and_role_instruction():
    prompt = build_post_prompt(VirtualRole.TECH_NEWS, "인기 주제: AI, 반도체")
    assert "인기 주제: AI, 반도체" in prompt
    assert "기술" in prompt  # tech_news instruction


def test_build_prompt_handles_empty_briefing():
    prompt = build_post_prompt(VirtualRole.DAILY, "")
    assert prompt  # falls back to a generic instruction
    assert "동향 정보" in prompt


def test_all_roles_have_distinct_prompts():
    prompts = {role: build_post_prompt(role, "공통 브리핑") for role in VirtualRole}
    # each role should produce a distinct instruction
    assert len(set(prompts.values())) == len(VirtualRole)
