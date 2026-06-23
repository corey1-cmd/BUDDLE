"""Security-hardening unit tests (Phase 3.1).

These pin the specific attack paths closed in this pass. All run in the fast
suite — no Postgres container — by exercising pure functions, the ASGI body
middleware directly, and config validation.

Covered:
  * Rate-limit IP resolution can't be spoofed via X-Forwarded-For.
  * Body-size middleware rejects oversize bodies (declared and streamed).
  * JWT decode enforces required claims / rejects alg=none.
  * Production config rejects dev secrets and wildcard CORS.
  * WebSocket Origin allowlist logic.
"""

from __future__ import annotations

import jwt
import pytest

# ── 1. Rate-limit IP spoofing (trusted-proxy strategies) ─────────────────────
#
# resolve_client_ip is a pure function — test the logic directly, no Settings.
from buddle.core.client_ip import diagnose_proxy_chain, resolve_client_ip

_PRIV = ["10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "127.0.0.0/8"]


def test_socket_mode_ignores_xff() -> None:
    """mode=socket → attacker XFF ignored, socket peer wins."""
    ip = resolve_client_ip(
        peer="10.0.0.9", xff="1.2.3.4, 5.6.7.8", mode="socket", trusted_cidrs=[], hops=0
    )
    assert ip == "10.0.0.9"


def test_auto_falls_back_to_socket_without_config() -> None:
    """mode=auto with no CIDRs and hops=0 behaves like socket."""
    ip = resolve_client_ip(
        peer="10.0.0.9", xff="1.2.3.4", mode="auto", trusted_cidrs=[], hops=0
    )
    assert ip == "10.0.0.9"


def test_cidr_mode_peels_trusted_hops() -> None:
    """One private proxy in front: client = entry left of the trusted tail."""
    # chain: client 203.0.113.7 → proxy 10.0.0.1 (rightmost). peer is the proxy.
    ip = resolve_client_ip(
        peer="10.0.0.1", xff="203.0.113.7, 10.0.0.1", mode="cidr",
        trusted_cidrs=_PRIV, hops=0,
    )
    assert ip == "203.0.113.7"


def test_cidr_mode_adapts_to_two_proxies_without_count() -> None:
    """Two private proxies: still resolves the real client — no hop count set.
    This is the whole point: the same config handles N proxies."""
    ip = resolve_client_ip(
        peer="10.0.0.2",
        xff="203.0.113.7, 10.0.0.1, 10.0.0.2",
        mode="cidr", trusted_cidrs=_PRIV, hops=0,
    )
    assert ip == "203.0.113.7"


def test_cidr_mode_spoofed_prefix_cannot_escape() -> None:
    """Attacker prepends fake public IPs; they sit LEFT of the genuine proxy
    tail, so the first-untrusted-from-right is the attacker's *outermost*
    injected hop — never the trusted segment. Two different spoof prefixes that
    keep the same genuine tail must NOT be mistaken for trusted infra."""
    a = resolve_client_ip(
        peer="10.0.0.1", xff="9.9.9.9, 203.0.113.7, 10.0.0.1",
        mode="cidr", trusted_cidrs=_PRIV, hops=0,
    )
    # Rightmost untrusted is 203.0.113.7 (the real client as seen by our proxy).
    assert a == "203.0.113.7"


def test_cidr_mode_untrusted_direct_peer_is_client() -> None:
    """If the socket peer itself is untrusted (app directly exposed), XFF is
    unverifiable hearsay → use the peer, ignore the header entirely."""
    ip = resolve_client_ip(
        peer="203.0.113.50", xff="1.2.3.4, 5.6.7.8",
        mode="cidr", trusted_cidrs=_PRIV, hops=0,
    )
    assert ip == "203.0.113.50"


def test_cidr_mode_handles_ip_with_port() -> None:
    """XFF tokens may carry :port; parsing must still work."""
    ip = resolve_client_ip(
        peer="10.0.0.1", xff="203.0.113.7:51234, 10.0.0.1:443",
        mode="cidr", trusted_cidrs=_PRIV, hops=0,
    )
    assert ip == "203.0.113.7"


def test_hops_mode_uses_entry_left_of_trusted_tail() -> None:
    ip = resolve_client_ip(
        peer="10.0.0.1", xff="203.0.113.7, 10.0.0.1",
        mode="hops", trusted_cidrs=[], hops=1,
    )
    assert ip == "203.0.113.7"


def test_hops_mode_rejects_too_short_chain() -> None:
    """Declared hops exceed the actual chain (forged/short) → fall back to peer,
    never honor the attacker-shaped header."""
    ip = resolve_client_ip(
        peer="10.0.0.1", xff="203.0.113.7",  # only 1 entry but we expect 3 hops
        mode="hops", trusted_cidrs=[], hops=3,
    )
    assert ip == "10.0.0.1"


def test_hops_mode_spoof_maps_to_same_slot() -> None:
    """Rotating a fake prefix under fixed hops still maps to the same real-client
    slot (no per-request bypass)."""
    a = resolve_client_ip(peer="10.0.0.1", xff="9.9.9.9, 203.0.113.7, 10.0.0.1",
                          mode="hops", trusted_cidrs=[], hops=1)
    b = resolve_client_ip(peer="10.0.0.1", xff="8.8.8.8, 203.0.113.7, 10.0.0.1",
                          mode="hops", trusted_cidrs=[], hops=1)
    assert a == b == "203.0.113.7"


def test_diagnose_reports_measured_hop_count() -> None:
    """The boot diagnostic turns 'guess your proxy count' into a measured value."""
    diag = diagnose_proxy_chain(
        peer="10.0.0.2",
        xff="203.0.113.7, 10.0.0.1, 10.0.0.2",
        trusted_cidrs=_PRIV,
    )
    assert diag["xff_chain_len"] == 3
    assert diag["trusted_hops_from_right"] == 2
    assert diag["equivalent_hops"] == 2
    assert diag["selected_client_ip_cidr_mode"] == "203.0.113.7"


def test_auto_selects_cidr_when_ranges_present() -> None:
    """mode=auto resolves to cidr once trusted ranges are configured —
    operators don't have to also flip the mode switch."""
    ip = resolve_client_ip(
        peer="10.0.0.1", xff="203.0.113.7, 10.0.0.1",
        mode="auto", trusted_cidrs=_PRIV, hops=0,
    )
    assert ip == "203.0.113.7"


def test_cidr_mode_handles_ipv6_ula() -> None:
    """IPv6 unique-local proxies (fc00::/7) are recognized as trusted infra."""
    ip = resolve_client_ip(
        peer="fc00::1",
        xff="2001:db8::abcd, fc00::1",
        mode="cidr", trusted_cidrs=["fc00::/7", "::1/128"], hops=0,
    )
    assert ip == "2001:db8::abcd"


def test_cidr_mode_without_ranges_falls_back_to_peer() -> None:
    """mode=cidr but no valid ranges configured → never trust XFF; use peer."""
    ip = resolve_client_ip(
        peer="10.0.0.1", xff="1.2.3.4, 5.6.7.8",
        mode="cidr", trusted_cidrs=[], hops=0,
    )
    assert ip == "10.0.0.1"


def test_hops_value_is_range_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    """trusted_proxy_hops is clamped to [0, 8] at the schema level."""
    from pydantic import ValidationError

    from buddle import config
    from buddle.config import Settings

    config.get_settings.cache_clear()
    monkeypatch.setenv("TRUSTED_PROXY_HOPS", "99")
    with pytest.raises(ValidationError):
        Settings()
    config.get_settings.cache_clear()


# ── 2. Body-size middleware ──────────────────────────────────────────────────


async def _drive(mw, body: bytes, content_length: int | None) -> tuple[int, bytes]:
    """Run one HTTP request through the ASGI middleware, return (status, body)."""
    headers = []
    if content_length is not None:
        headers.append((b"content-length", str(content_length).encode()))
    scope = {"type": "http", "method": "POST", "path": "/x", "headers": headers}

    sent = {"body": b""}
    started = {"status": 0}

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    async def send(message):
        if message["type"] == "http.response.start":
            started["status"] = message["status"]
        elif message["type"] == "http.response.body":
            sent["body"] += message.get("body", b"")

    await mw(scope, receive, send)
    return started["status"], sent["body"]


async def _ok_app(scope, receive, send):
    # Read the body, then 200 — mimics a normal handler.
    await receive()
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await send({"type": "http.response.body", "body": b"ok"})


async def test_body_limit_rejects_declared_oversize() -> None:
    from buddle.core.body_limit import BodySizeLimitMiddleware

    mw = BodySizeLimitMiddleware(_ok_app, max_body_bytes=100)
    status, body = await _drive(mw, body=b"x" * 50, content_length=10_000)
    assert status == 413
    assert b"PAYLOAD_TOO_LARGE" in body


async def test_body_limit_rejects_streamed_oversize_without_content_length() -> None:
    """No Content-Length (chunked) but body exceeds cap → 413 via streaming guard."""
    from buddle.core.body_limit import BodySizeLimitMiddleware

    mw = BodySizeLimitMiddleware(_ok_app, max_body_bytes=100)
    status, body = await _drive(mw, body=b"x" * 500, content_length=None)
    assert status == 413
    assert b"PAYLOAD_TOO_LARGE" in body


async def test_body_limit_allows_within_cap() -> None:
    from buddle.core.body_limit import BodySizeLimitMiddleware

    mw = BodySizeLimitMiddleware(_ok_app, max_body_bytes=1000)
    status, body = await _drive(mw, body=b"x" * 50, content_length=50)
    assert status == 200
    assert body == b"ok"


# ── 3. JWT hardening ─────────────────────────────────────────────────────────


def test_jwt_rejects_alg_none(monkeypatch: pytest.MonkeyPatch) -> None:
    """A token forged with alg=none must be rejected (no signature trust)."""
    from buddle.core.exceptions import Unauthorized
    from buddle.security.jwt import decode_token

    forged = jwt.encode(
        {"sub": "u", "type": "access", "iat": 0, "exp": 9_999_999_999},
        key="",
        algorithm="none",
    )
    with pytest.raises(Unauthorized):
        decode_token(forged)


def test_jwt_rejects_missing_required_claims() -> None:
    """A signature-valid token lacking required claims (no sub/type) is rejected."""
    from buddle.config import get_settings
    from buddle.core.exceptions import Unauthorized
    from buddle.security.jwt import decode_token

    secret = get_settings().jwt_secret_key.get_secret_value()
    # valid signature, but missing 'sub' and 'type'
    tok = jwt.encode({"iat": 0, "exp": 9_999_999_999}, secret, algorithm="HS256")
    with pytest.raises(Unauthorized):
        decode_token(tok)


def test_jwt_roundtrip_still_valid() -> None:
    from buddle.security.jwt import create_access_token, decode_token

    tok = create_access_token("11111111-1111-1111-1111-111111111111")
    claims = decode_token(tok)
    assert claims["type"] == "access"
    assert claims["sub"] == "11111111-1111-1111-1111-111111111111"


# ── 4. Production config guards ──────────────────────────────────────────────


def _prod_env(monkeypatch: pytest.MonkeyPatch, **over: str) -> None:
    from buddle import config

    config.get_settings.cache_clear()
    base = {
        "APP_ENV": "production",
        "JWT_SECRET_KEY": "x" * 44,
        "INTEGRITY_HMAC_KEY": "y" * 44,
        "CORS_ORIGINS": "https://buddle.app",
    }
    base.update(over)
    for k, v in base.items():
        monkeypatch.setenv(k, v)


def test_prod_rejects_wildcard_cors(monkeypatch: pytest.MonkeyPatch) -> None:
    from buddle.config import Settings

    _prod_env(monkeypatch, CORS_ORIGINS="*")
    with pytest.raises(Exception) as ei:
        Settings()
    assert "cors_origins" in str(ei.value)
    from buddle import config

    config.get_settings.cache_clear()


def test_prod_rejects_dev_jwt_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    from buddle.config import Settings

    _prod_env(monkeypatch, JWT_SECRET_KEY="dev_only_change_in_production_______")
    with pytest.raises(Exception) as ei:
        Settings()
    assert "jwt_secret_key" in str(ei.value)
    from buddle import config

    config.get_settings.cache_clear()


def test_prod_accepts_strong_distinct_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    from buddle.config import Settings

    _prod_env(monkeypatch)
    s = Settings()  # should not raise
    assert s.app_env == "production"
    from buddle import config

    config.get_settings.cache_clear()


def test_prod_rejects_cidr_mode_without_ranges(monkeypatch: pytest.MonkeyPatch) -> None:
    """mode=cidr with no ranges would silently fall back to socket and bucket
    every user together — production refuses to start instead."""
    from buddle.config import Settings

    _prod_env(monkeypatch, TRUSTED_PROXY_MODE="cidr", TRUSTED_PROXY_CIDRS="")
    with pytest.raises(Exception) as ei:
        Settings()
    assert "trusted_proxy_cidrs" in str(ei.value)
    from buddle import config

    config.get_settings.cache_clear()


def test_prod_rejects_hops_mode_without_count(monkeypatch: pytest.MonkeyPatch) -> None:
    """mode=hops with hops=0 is the same silent-fallback footgun → refused."""
    from buddle.config import Settings

    _prod_env(monkeypatch, TRUSTED_PROXY_MODE="hops", TRUSTED_PROXY_HOPS="0")
    with pytest.raises(Exception) as ei:
        Settings()
    assert "trusted_proxy_hops" in str(ei.value)
    from buddle import config

    config.get_settings.cache_clear()


# ── 5. WebSocket Origin allowlist ────────────────────────────────────────────


class _WS:
    def __init__(self, origin: str | None) -> None:
        headers = []
        if origin is not None:
            headers.append((b"origin", origin.encode()))
        self.scope = {"headers": headers}


def test_ws_origin_allowed_for_listed(monkeypatch: pytest.MonkeyPatch) -> None:
    from buddle import config
    from buddle.api.v1 import dialogue

    config.get_settings.cache_clear()
    monkeypatch.setenv("WS_ALLOWED_ORIGINS", "https://buddle.app")
    assert dialogue._ws_origin_allowed(_WS("https://buddle.app")) is True  # type: ignore[arg-type]
    config.get_settings.cache_clear()


def test_ws_origin_blocked_for_cross_site(monkeypatch: pytest.MonkeyPatch) -> None:
    from buddle import config
    from buddle.api.v1 import dialogue

    config.get_settings.cache_clear()
    monkeypatch.setenv("WS_ALLOWED_ORIGINS", "https://buddle.app")
    assert dialogue._ws_origin_allowed(_WS("https://evil.example")) is False  # type: ignore[arg-type]
    config.get_settings.cache_clear()


def test_ws_missing_origin_follows_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    from buddle import config
    from buddle.api.v1 import dialogue

    config.get_settings.cache_clear()
    monkeypatch.setenv("WS_ALLOW_MISSING_ORIGIN", "false")
    monkeypatch.setenv("WS_ALLOWED_ORIGINS", "https://buddle.app")
    assert dialogue._ws_origin_allowed(_WS(None)) is False  # type: ignore[arg-type]
    config.get_settings.cache_clear()
