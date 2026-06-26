"""Persona backend adapter + factory tests.

Strategy:
  - VllmEndpointPersona is exercised against a stubbed httpx transport so
    we can assert exact request shape (model name, LoRA, headers) and
    response handling without needing a real LLM server.
  - PersonaService factory tests: cache hit, backend dispatch, fallback to
    stub on PersonaBackendError.
"""

from __future__ import annotations

import json

import httpx
import pytest

from buddle.ai.interfaces import DialogueTurn
from buddle.ai.personas import (
    PersonaBackendError,
    PersonaService,
    VllmEndpointPersona,
)

pytestmark = pytest.mark.asyncio


# ── VllmEndpointPersona ────────────────────────────────────────────────


def _mock_transport(handler):  # type: ignore[no-untyped-def]
    """Build an httpx.MockTransport that the adapter will pick up via
    monkeypatched AsyncClient. We monkeypatch by replacing the AsyncClient
    constructor that the adapter uses."""
    return httpx.MockTransport(handler)


async def test_vllm_endpoint_happy_path(monkeypatch):  # type: ignore[no-untyped-def]
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["json"] = json.loads(request.content.decode())
        captured["auth"] = request.headers.get("authorization")
        return httpx.Response(
            200,
            json={"choices": [{"message": {"role": "assistant", "content": "시인의 답신"}}]},
        )

    transport = _mock_transport(handler)

    # Monkeypatch httpx.AsyncClient so the adapter's `async with` uses our transport
    import buddle.ai.personas.vllm_endpoint as mod

    original_cls = mod.httpx.AsyncClient

    def patched_async_client(*args, **kwargs):  # type: ignore[no-untyped-def]
        kwargs["transport"] = transport
        return original_cls(*args, **kwargs)

    monkeypatch.setattr(mod.httpx, "AsyncClient", patched_async_client)

    adapter = VllmEndpointPersona(
        model_key="qwen3-poet-v2",
        system_prompt="당신은 시인입니다.",
        config={
            "endpoint_url": "https://vllm.test/v1",
            "model": "qwen3-7b-instruct",
            "lora_adapter": "buddle/poet-v2",
            "api_key": "secret",
            "temperature": 0.5,
            "max_tokens": 256,
        },
    )

    result = await adapter.interpret(
        persona_name="내 시인",
        model_key="qwen3-poet-v2",
        content_raw="오늘 하늘이 너무 파랗다",
    )

    assert result.content_transformed == "시인의 답신"
    assert result.metadata["backend"] == "vllm_endpoint"
    assert result.metadata["served_model"] == "qwen3-7b-instruct"

    # Request shape
    assert captured["url"] == "https://vllm.test/v1/chat/completions"
    assert captured["auth"] == "Bearer secret"
    body = captured["json"]
    assert body["model"] == "qwen3-7b-instruct"
    assert body["temperature"] == 0.5
    assert body["max_tokens"] == 256
    assert body["stream"] is False
    assert body["lora_request"] == {"lora_name": "buddle/poet-v2"}
    # System prompt + instruction + user content
    msgs = body["messages"]
    assert msgs[0]["role"] == "system"
    assert "시인" in msgs[0]["content"]
    assert msgs[-1]["role"] == "user"
    assert "오늘 하늘이 너무 파랗다" in msgs[-1]["content"]


async def test_vllm_endpoint_dialogue_renders_history(monkeypatch):  # type: ignore[no-untyped-def]
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["json"] = json.loads(request.content.decode())
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "이어 말해줄게요."}}]},
        )

    import buddle.ai.personas.vllm_endpoint as mod

    original_cls = mod.httpx.AsyncClient
    transport = _mock_transport(handler)
    monkeypatch.setattr(
        mod.httpx,
        "AsyncClient",
        lambda *a, **kw: original_cls(*a, **{**kw, "transport": transport}),
    )

    adapter = VllmEndpointPersona(
        model_key="qwen3-poet-v2",
        system_prompt="당신은 시인입니다.",
        config={"endpoint_url": "https://vllm.test/v1", "model": "qwen3-7b-instruct"},
    )

    history = [
        DialogueTurn(role="user", content="안녕"),
        DialogueTurn(role="persona", content="안녕하세요."),
        DialogueTurn(role="mediator_bundle", content="여행 관련 글이 인기"),
    ]
    reply = await adapter.respond_in_dialogue(
        persona_name="내 시인",
        model_key="qwen3-poet-v2",
        history=history,
        user_message="오늘 어땠어요?",
    )

    assert reply.content == "이어 말해줄게요."
    msgs = captured["json"]["messages"]
    roles = [m["role"] for m in msgs]
    # system, user, assistant, system(bundle), then a cognition guidance system
    # block (injected when cognition_enabled), then the user message last.
    assert roles[:4] == ["system", "user", "assistant", "system"]
    assert roles[-1] == "user"
    assert "여행 관련 글이 인기" in msgs[3]["content"]
    assert msgs[-1]["content"] == "오늘 어땠어요?"
    # the cognition block carries the analysis header
    assert any("인지 분석" in m["content"] for m in msgs if m["role"] == "system")


async def test_vllm_endpoint_5xx_raises_persona_backend_error(monkeypatch):  # type: ignore[no-untyped-def]
    call_count = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        return httpx.Response(503, text="upstream down")

    import buddle.ai.personas.vllm_endpoint as mod

    original_cls = mod.httpx.AsyncClient
    transport = _mock_transport(handler)
    monkeypatch.setattr(
        mod.httpx,
        "AsyncClient",
        lambda *a, **kw: original_cls(*a, **{**kw, "transport": transport}),
    )

    adapter = VllmEndpointPersona(
        model_key="x",
        system_prompt=None,
        config={"endpoint_url": "https://vllm.test/v1", "model": "m"},
    )

    with pytest.raises(PersonaBackendError):
        await adapter.interpret(persona_name="x", model_key="x", content_raw="y")

    # Adapter retries once: 1 initial + 1 retry = 2 attempts
    assert call_count["n"] == 2


async def test_vllm_endpoint_missing_config_rejected():
    with pytest.raises(PersonaBackendError):
        VllmEndpointPersona(model_key="x", system_prompt=None, config={})
    with pytest.raises(PersonaBackendError):
        VllmEndpointPersona(
            model_key="x",
            system_prompt=None,
            config={"endpoint_url": "https://x/v1"},  # missing 'model'
        )


# ── PersonaService factory ────────────────────────────────────────────


async def test_persona_service_falls_back_to_stub_on_backend_error(  # type: ignore[no-untyped-def]
    db_session, signup_and_login, client
):
    """If a vllm_endpoint model is registered with a bogus endpoint, the
    service should silently fall back to PersonaStub for the user."""
    import uuid as _uuid

    from sqlalchemy import update

    from buddle.db.models.enums import (
        UserTier,
    )
    from buddle.db.models.user import User

    # Make an admin out of a fresh signup
    info = await signup_and_login()
    await db_session.execute(
        update(User)
        .where(User.id == _uuid.UUID(info["user_id"]))
        .values(is_admin=True, tier=UserTier.PRO)
    )
    await db_session.commit()

    # Re-login as admin
    r = await client.post(
        "/v1/auth/login",
        json={"email": info["email"], "password": info["password"]},
    )
    admin_token = r.json()["access_token"]
    ah = {"Authorization": f"Bearer {admin_token}"}

    # Register a vllm_endpoint model pointing at an unreachable host
    r = await client.post(
        "/v1/admin/persona-models",
        json={
            "template_key": "broken-vllm",
            "display_name": "고장난 시인",
            "backend_kind": "vllm_endpoint",
            "backend_config": {
                # private (allowed in tests) but unreachable -> backend call
                # fails -> factory falls back to stub. (loopback 127.0.0.1 is
                # ALWAYS SSRF-blocked regardless of allow_private, so we can't
                # use it here.)
                "endpoint_url": "http://10.255.255.1:1/v1",
                "model": "x",
                "timeout_s": 1,
            },
            "status": "active",
        },
        headers=ah,
    )
    assert r.status_code == 201, r.text

    # A regular user creates a persona on it
    user = await signup_and_login()
    uh = {"Authorization": f"Bearer {user['access_token']}"}
    r = await client.post(
        "/v1/personas",
        json={"name": "테스트", "model_key": "broken-vllm"},
        headers=uh,
    )
    assert r.status_code == 201
    persona_id = r.json()["id"]

    # Post creation must succeed because the factory falls back to stub
    r = await client.post(
        "/v1/posts",
        json={"persona_id": persona_id, "content_raw": "안녕", "visibility": "public"},
        headers=uh,
    )
    assert r.status_code == 201, r.text
    # Stub prefix uses display_name
    assert r.json()["content_transformed"].startswith("[고장난 시인]")


async def test_persona_service_caches_interpret_result(db_session):  # type: ignore[no-untyped-def]
    """Two interpret() calls with the same input should hit the cache on the second."""
    import fakeredis.aioredis

    fake = fakeredis.aioredis.FakeRedis(decode_responses=True)
    svc = PersonaService(db_session, fake)

    # Use the 'poet' stub model that the migration seeded
    first = await svc.interpret(
        persona_name="시인이",
        model_key="poet",
        content_raw="동일한 입력 텍스트",
    )
    second = await svc.interpret(
        persona_name="시인이",
        model_key="poet",
        content_raw="동일한 입력 텍스트",
    )

    assert first.content_transformed == second.content_transformed
    assert second.metadata.get("cache_hit") == "true"

    await fake.aclose()
