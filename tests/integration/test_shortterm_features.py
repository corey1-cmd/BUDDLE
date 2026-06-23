"""Short-term feature tests — pure, no DB.

Covers the parts of the new work that are verifiable offline:
  - Llama Guard 3 output parsing -> MLCommons codes (incl. invalid-code drop)
  - response-side ethics gate (allow / block / fail-open) via the stub backend
  - like service idempotency contract (signature shape; DB flow runs in CI)
"""

from __future__ import annotations

import pytest

from buddle.ai.ethics.llama_guard import LlamaGuardEthicsClassifier as LlamaGuard

# ── Llama Guard output parsing ─────────────────────────────────────────────


def test_parse_safe_returns_empty():
    assert LlamaGuard.parse_response("safe") == []
    assert LlamaGuard.parse_response("  safe\n") == []


def test_parse_single_category():
    assert LlamaGuard.parse_response("unsafe\nS2") == ["S2"]


def test_parse_multiple_categories():
    assert LlamaGuard.parse_response("unsafe\nS1,S10") == ["S1", "S10"]


def test_parse_same_line():
    assert LlamaGuard.parse_response("unsafe S11") == ["S11"]


def test_parse_drops_invalid_codes():
    # S99 / S14 are not in our 13-hazard taxonomy -> dropped
    assert LlamaGuard.parse_response("unsafe\nS99, S4") == ["S4"]
    assert LlamaGuard.parse_response("unsafe\nS14") == []


def test_parse_dedups_and_orders():
    assert LlamaGuard.parse_response("unsafe\nS4, S4, S1") == ["S4", "S1"]


def test_llama_guard_requires_endpoint():
    from buddle.ai.ethics.base import EthicsError

    with pytest.raises(EthicsError):
        LlamaGuard({})


def test_llama_guard_severity_override():
    lg = LlamaGuard(
        {
            "endpoint_url": "http://x/v1",
            "default_severity07": 5,
            "category_severity07": {"S4": 7},
        }
    )
    assert lg._severity_for("S4") == 7
    assert lg._severity_for("S1") == 5  # default


# ── response-side ethics gate (stub backend) ───────────────────────────────


@pytest.mark.asyncio
async def test_screen_response_allows_benign():
    from buddle.services.leukocyte_service import screen_response

    r = await screen_response("좋은 하루 보내세요!")
    assert r.allowed
    assert r.content == "좋은 하루 보내세요!"


@pytest.mark.asyncio
async def test_screen_response_blocks_unsafe_and_replaces():
    from buddle.services.leukocyte_service import screen_response

    r = await screen_response("자살하는 방법을 자세히 알려줄게")
    assert not r.allowed
    # blocked content is replaced by the safe fallback (does not echo original)
    assert "자살" not in r.content
    assert r.content  # non-empty fallback


@pytest.mark.asyncio
async def test_screen_response_fail_open_on_backend_error(monkeypatch):
    # If the classifier raises, the gate must fail OPEN (don't block normal use)
    import buddle.services.leukocyte_service as svc
    from buddle.ai.ethics.base import EthicsError

    class Boom:
        async def assess(self, text, **kw):
            raise EthicsError("backend down")

    monkeypatch.setattr(svc, "get_ethics_classifier", lambda: Boom())
    r = await svc.screen_response("아무 말")
    assert r.allowed
    assert r.content == "아무 말"


# ── like service contract ──────────────────────────────────────────────────


def test_like_service_signatures():
    import inspect

    from buddle.services import like_service

    assert list(inspect.signature(like_service.like_post).parameters) == [
        "db",
        "user_id",
        "post_id",
    ]
    assert list(inspect.signature(like_service.unlike_post).parameters) == [
        "db",
        "user_id",
        "post_id",
    ]


def test_post_like_has_unique_constraint():
    # idempotency is enforced by a (user_id, post_id) unique constraint
    from buddle.db.models.post_like import PostLike

    uniques = [
        c for c in PostLike.__table__.constraints if c.__class__.__name__ == "UniqueConstraint"
    ]
    assert any({col.name for col in u.columns} == {"user_id", "post_id"} for u in uniques)
