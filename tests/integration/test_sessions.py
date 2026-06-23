"""Conversation session tests — model/schema/service contracts (no DB).

The full create/list/message-history flow runs against Postgres in CI. Here we
verify the model shape, schema validation, service signatures, and that
dialogue history loading accepts a session scope.
"""

from __future__ import annotations

import inspect

import pytest

# ── model ──────────────────────────────────────────────────────────────────


def test_session_model_columns():
    from buddle.db.models.conversation_session import ConversationSession

    cols = set(ConversationSession.__table__.columns.keys())
    assert {"id", "persona_id", "title", "topic", "created_at", "last_active_at"} <= cols


def test_message_has_session_fk():
    from buddle.db.models.message import Message

    assert "session_id" in Message.__table__.columns
    # nullable for backward compat with pre-session messages
    assert Message.__table__.columns["session_id"].nullable


# ── schema validation ────────────────────────────────────────────────────


def test_session_create_requires_title():
    from pydantic import ValidationError

    from buddle.api.v1.sessions import SessionCreate

    SessionCreate(title="여행 얘기", topic="travel")
    with pytest.raises(ValidationError):
        SessionCreate(title="")


def test_session_create_topic_optional():
    from buddle.api.v1.sessions import SessionCreate

    s = SessionCreate(title="제목만")
    assert s.topic is None


def test_client_message_carries_optional_session():
    from buddle.schemas.dialogue import ClientUserMessage

    # session omitted -> None (backward compatible)
    m1 = ClientUserMessage(type="user_message", content="안녕")
    assert m1.session_id is None
    # session provided
    import uuid

    sid = uuid.uuid4()
    m2 = ClientUserMessage(type="user_message", content="안녕", session_id=sid)
    assert m2.session_id == sid


# ── service signatures ─────────────────────────────────────────────────────


def test_session_service_signatures():
    from buddle.services import conversation_session_service as css

    assert "title" in inspect.signature(css.create_session).parameters
    assert "topic" in inspect.signature(css.create_session).parameters


def test_dialogue_history_accepts_session_scope():
    from buddle.services import dialogue_service

    params = inspect.signature(dialogue_service.load_recent_history).parameters
    assert "session_id" in params
    # record fns also accept session_id
    assert "session_id" in inspect.signature(dialogue_service.record_user_message).parameters
    assert "session_id" in inspect.signature(dialogue_service.record_persona_message).parameters


def test_conversation_session_service_distinct_from_metrics():
    # ensure we didn't collide with the engagement-metrics session_service
    from buddle.services import conversation_session_service, session_service

    assert conversation_session_service is not session_service
