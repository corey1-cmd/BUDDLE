"""Plaza Part 2 tests — agent key crypto, schema validation, enums.

The DB-backed flows (posting through the ingestion pipeline, comments) need
Postgres and run in CI. Here we cover what's verifiable offline: the agent
API-key generation/verification crypto, schema validation, and enum wiring.
"""

from __future__ import annotations

import pytest

from buddle.db.models.enums import AgentKind, AuthorKind, CommentKind

# ── enums ────────────────────────────────────────────────────────────────


def test_author_kind_values():
    assert AuthorKind.HUMAN == "human"
    assert AuthorKind.PERSONA_AI == "persona_ai"
    assert AuthorKind.EXTERNAL_AI == "external_ai"
    assert AuthorKind.BOT == "bot"


def test_comment_kind_values():
    assert {c.value for c in CommentKind} == {"inform", "empathize", "question"}


def test_agent_kind_values():
    assert "news" in {k.value for k in AgentKind}
    assert "qna" in {k.value for k in AgentKind}


# ── agent API key crypto ─────────────────────────────────────────────────


def test_agent_key_generation_is_prefixed_and_unique():
    from buddle.services.agent_service import _KEY_PREFIX, _generate_api_key

    k1 = _generate_api_key()
    k2 = _generate_api_key()
    assert k1.startswith(_KEY_PREFIX)
    assert k1 != k2
    assert len(k1) > len(_KEY_PREFIX) + 20  # has real entropy


def test_agent_key_hash_roundtrip():
    """A generated key verifies against its hash; a wrong key does not."""
    from buddle.security.password import hash_password, verify_password
    from buddle.services.agent_service import _generate_api_key

    key = _generate_api_key()
    h = hash_password(key)
    assert verify_password(key, h)
    assert not verify_password("bdl_agent_wrong", h)


def test_agent_key_hash_not_plaintext():
    from buddle.security.password import hash_password
    from buddle.services.agent_service import _generate_api_key

    key = _generate_api_key()
    h = hash_password(key)
    assert key not in h  # the hash must not contain the plaintext


# ── schema validation ────────────────────────────────────────────────────


def test_agent_register_request_clamps_trust_tier():
    from pydantic import ValidationError

    from buddle.schemas.plaza import AgentRegisterRequest

    # valid
    r = AgentRegisterRequest(name="News Agent", kind=AgentKind.NEWS, trust_tier=2)
    assert r.trust_tier == 2
    # out of range rejected
    with pytest.raises(ValidationError):
        AgentRegisterRequest(name="X", kind=AgentKind.NEWS, trust_tier=9)


def test_agent_post_request_requires_content():
    from pydantic import ValidationError

    from buddle.schemas.plaza import AgentPostRequest

    with pytest.raises(ValidationError):
        AgentPostRequest(content="")


def test_comment_request_kind_enum():
    from buddle.schemas.plaza import CommentCreateRequest

    c = CommentCreateRequest(kind=CommentKind.QUESTION, content="이거 왜 그런거야?")
    assert c.kind == CommentKind.QUESTION


def test_comment_request_rejects_overlong():
    from pydantic import ValidationError

    from buddle.schemas.plaza import CommentCreateRequest

    with pytest.raises(ValidationError):
        CommentCreateRequest(kind=CommentKind.INFORM, content="x" * 5000)
