"""LLM contract + degraded-mode tests for the news mediator and user-context.

The live endpoint (Gemini free tier) can't be exercised in CI, so we mock the
OpenAI-compatible HTTP layer to pin down BOTH the happy 200 path (JSON parsed
into a MediatedArticle / UserContextFact) and the degraded paths:
  - 429 (rate limit): retried with backoff, then graceful fallback to a stub.
  - 400 on response_format: transparently dropped and retried.
"""

from __future__ import annotations

import json

import httpx
import pytest

from buddle.ai.news import mediator as M
from buddle.ai.news.fetcher import RawArticle


class _Resp:
    def __init__(self, status: int, content: str = "", headers: dict | None = None):
        self.status_code = status
        self._content = content
        self.headers = headers or {}

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("err", request=None, response=None)  # type: ignore[arg-type]

    def json(self) -> dict:
        return {"choices": [{"message": {"content": self._content}}]}


class _Client:
    """Stand-in for httpx.AsyncClient yielding a scripted sequence of responses."""

    def __init__(self, responses: list[_Resp]):
        self._responses = responses
        self.calls = 0

    async def __aenter__(self) -> "_Client":
        return self

    async def __aexit__(self, *a: object) -> bool:
        return False

    async def post(self, url: str, json: object = None, headers: object = None) -> _Resp:
        r = self._responses[min(self.calls, len(self._responses) - 1)]
        self.calls += 1
        return r


class _Settings:
    persona_endpoint_url = "https://example.test/v1"
    persona_endpoint_api_key = "k"
    persona_model = "test-model"


def _patch(monkeypatch, responses: list[_Resp]) -> _Client:
    client = _Client(responses)
    monkeypatch.setattr(M.httpx, "AsyncClient", lambda *a, **k: client)

    async def _no_sleep(_: float) -> None:
        return None

    monkeypatch.setattr(M.asyncio, "sleep", _no_sleep)
    return client


_ART = RawArticle(url="https://x/y", title="GPT-5 released", source="hackernews")


@pytest.mark.asyncio
async def test_mediator_parses_200_json(monkeypatch):
    payload = json.dumps(
        {"gist_ko": "GPT-5가 출시됐다.", "tags": ["AI", "LLM"],
         "ekb_stage_a": "주의/이해/수용", "ekb_briefing": "최신 AI 소식", "relevance": 0.9},
        ensure_ascii=False,
    )
    _patch(monkeypatch, [_Resp(200, payload)])
    med = await M.analyse_article(_ART, settings=_Settings())
    assert med.stub is False
    assert med.gist_ko == "GPT-5가 출시됐다."
    assert med.tags == ["AI", "LLM"]
    assert med.relevance == pytest.approx(0.9)


@pytest.mark.asyncio
async def test_mediator_429_retries_then_degrades(monkeypatch):
    client = _patch(monkeypatch, [_Resp(429), _Resp(429), _Resp(429), _Resp(429)])
    med = await M.analyse_article(_ART, settings=_Settings())
    assert med.stub is True  # graceful fallback
    assert client.calls == M._MAX_ATTEMPTS  # retried, not one-shot


@pytest.mark.asyncio
async def test_mediator_400_drops_response_format_then_succeeds(monkeypatch):
    payload = json.dumps({"gist_ko": "ok", "tags": ["AI"], "relevance": 0.7}, ensure_ascii=False)
    # First call 400 (json mode unsupported) -> retry without it -> 200.
    _patch(monkeypatch, [_Resp(400), _Resp(200, payload)])
    med = await M.analyse_article(_ART, settings=_Settings())
    assert med.stub is False
    assert med.gist_ko == "ok"


@pytest.mark.asyncio
async def test_mediator_no_endpoint_is_stub(monkeypatch):
    class _NoEp:
        persona_endpoint_url = ""
        persona_endpoint_api_key = ""
        persona_model = "x"

    med = await M.analyse_article(_ART, settings=_NoEp())
    assert med.stub is True


@pytest.mark.asyncio
async def test_user_context_parses_and_degrades(monkeypatch):
    from buddle.services import user_context_service as UC

    # happy path: clear disclosure + a 200 returning facts
    payload = json.dumps(
        {"name": "민수", "age": 29, "location": "서울", "occupation": None, "interests": ["등산"]},
        ensure_ascii=False,
    )
    monkeypatch.setattr(UC.httpx, "AsyncClient", lambda *a, **k: _Client([_Resp(200, payload)]))
    fact = await UC.extract_facts_llm("제 이름은 민수입니다", settings=_Settings())
    assert fact.name == "민수" and fact.location == "서울"

    # degraded: endpoint errors -> empty fact (never the wrong regex facts)
    monkeypatch.setattr(UC.httpx, "AsyncClient", lambda *a, **k: _Client([_Resp(500)]))
    fact2 = await UC.extract_facts_llm("제 이름은 민수입니다", settings=_Settings())
    assert fact2.name is None
