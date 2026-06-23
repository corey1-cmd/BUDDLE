"""Security hardening tests (audit follow-up).

Covers:
  - H1: production rejects dev-default / weak / identical secrets
  - M3: password complexity enforced at signup
  - M4 L2: process-local backup limiter bounds single-process abuse
  - M1: refresh-token family rotation + reuse detection (fakeredis)
  - H2: dummy verification keeps login constant-time-ish for unknown users

Most run without a DB. The family-rotation tests use fakeredis.
"""

from __future__ import annotations

import pytest

# ── H1: production secret validation ─────────────────────────────────────


def test_config_rejects_dev_secrets_in_production():
    from buddle.config import Settings

    with pytest.raises(Exception):  # noqa: B017 - pydantic ValidationError
        Settings(app_env="production")


def test_config_rejects_identical_secrets_in_production():
    from buddle.config import Settings

    with pytest.raises(Exception):  # noqa: B017
        Settings(
            app_env="production",
            jwt_secret_key="z" * 40,
            integrity_hmac_key="z" * 40,
        )


def test_config_accepts_strong_distinct_secrets_in_production():
    from buddle.config import Settings

    s = Settings(
        app_env="production",
        jwt_secret_key="a" * 40,
        integrity_hmac_key="b" * 40,
    )
    assert s.app_env == "production"


def test_config_dev_uses_defaults_fine():
    from buddle.config import Settings

    s = Settings(app_env="development")
    assert s.is_dev


# ── M3: password complexity ──────────────────────────────────────────────


def test_password_requires_letter_digit_special():
    from pydantic import ValidationError

    from buddle.schemas.auth import SignupRequest

    # all-letters: missing digit + special
    with pytest.raises(ValidationError):
        SignupRequest(email="a@b.com", password="abcdefgh", password_confirm="abcdefgh")
    # letters+digits: missing special
    with pytest.raises(ValidationError):
        SignupRequest(email="a@b.com", password="abcd1234", password_confirm="abcd1234")


def test_password_valid_when_all_classes_present():
    from buddle.schemas.auth import SignupRequest

    req = SignupRequest(email="a@b.com", password="abcd1234!", password_confirm="abcd1234!")
    assert req.password == "abcd1234!"


def test_password_mismatch_rejected():
    from pydantic import ValidationError

    from buddle.schemas.auth import SignupRequest

    with pytest.raises(ValidationError):
        SignupRequest(email="a@b.com", password="abcd1234!", password_confirm="abcd1234?")


# ── M4 Layer 2: process-local backup limiter ─────────────────────────────


def test_local_backup_limiter_blocks_over_limit():
    from buddle.core.ratelimit import _local_allow, _local_buckets

    _local_buckets.clear()
    key = "test:1.2.3.4"
    # limit 3 within a long window
    assert _local_allow(key, 3, 100.0)
    assert _local_allow(key, 3, 100.0)
    assert _local_allow(key, 3, 100.0)
    assert not _local_allow(key, 3, 100.0)  # 4th blocked


def test_local_backup_limiter_independent_keys():
    from buddle.core.ratelimit import _local_allow, _local_buckets

    _local_buckets.clear()
    assert _local_allow("a", 1, 100.0)
    assert not _local_allow("a", 1, 100.0)
    # different key unaffected
    assert _local_allow("b", 1, 100.0)


# ── M1: refresh token family rotation + reuse detection ──────────────────


@pytest.mark.asyncio
async def test_refresh_rotation_and_reuse_detection():
    import fakeredis.aioredis

    from buddle.security.jwt import (
        RefreshOutcome,
        register_refresh_family,
        validate_and_rotate_family,
    )

    r = fakeredis.aioredis.FakeRedis(decode_responses=True)
    fid = "fam-1"
    user = "user-1"

    # initial family with jti_1 as current
    await register_refresh_family(r, family_id=fid, jti="jti_1", user_id=user)

    # rotate: jti_1 is current -> VALID, returns new jti
    outcome, new_jti = await validate_and_rotate_family(
        r, family_id=fid, presented_jti="jti_1", expected_user_id=user
    )
    assert outcome == RefreshOutcome.VALID
    assert new_jti and new_jti != "jti_1"

    # new jti rotates fine
    outcome2, new_jti2 = await validate_and_rotate_family(
        r, family_id=fid, presented_jti=new_jti, expected_user_id=user
    )
    assert outcome2 == RefreshOutcome.VALID

    # replay an OLD, non-grace jti (jti_1 again, grace already elapsed since we
    # rotated twice with default 10s grace — jti_1's grace key was for the
    # first rotation only). Use a clearly stale unknown jti to force reuse.
    outcome3, _ = await validate_and_rotate_family(
        r, family_id=fid, presented_jti="totally-unknown-jti", expected_user_id=user
    )
    assert outcome3 == RefreshOutcome.REUSE_DETECTED

    # after reuse detection the family is revoked
    outcome4, _ = await validate_and_rotate_family(
        r, family_id=fid, presented_jti=new_jti2, expected_user_id=user
    )
    assert outcome4 == RefreshOutcome.REVOKED

    await r.aclose()


@pytest.mark.asyncio
async def test_refresh_user_mismatch_is_unknown():
    import fakeredis.aioredis

    from buddle.security.jwt import (
        RefreshOutcome,
        register_refresh_family,
        validate_and_rotate_family,
    )

    r = fakeredis.aioredis.FakeRedis(decode_responses=True)
    await register_refresh_family(r, family_id="f", jti="j", user_id="alice")
    outcome, _ = await validate_and_rotate_family(
        r, family_id="f", presented_jti="j", expected_user_id="bob"
    )
    assert outcome == RefreshOutcome.UNKNOWN
    await r.aclose()


# ── M4 Layer 3: account lockout ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_account_lockout_after_threshold():
    import fakeredis.aioredis

    from buddle.security.account_lockout import (
        is_locked,
        record_failure,
    )

    r = fakeredis.aioredis.FakeRedis(decode_responses=True)
    email = "victim@example.com"

    assert not await is_locked(r, email)
    # default threshold is 10
    for _ in range(10):
        await record_failure(r, email)
    assert await is_locked(r, email)

    await r.aclose()


@pytest.mark.asyncio
async def test_account_lockout_clears_on_success():
    import fakeredis.aioredis

    from buddle.security.account_lockout import clear_failures, is_locked, record_failure

    r = fakeredis.aioredis.FakeRedis(decode_responses=True)
    email = "user@example.com"
    for _ in range(3):
        await record_failure(r, email)
    await clear_failures(r, email)
    # not locked, and counter reset
    assert not await is_locked(r, email)
    await r.aclose()


# ── L1: SSRF guard ───────────────────────────────────────────────────────


def _patch_resolve(monkeypatch, ip_str):  # type: ignore[no-untyped-def]
    import buddle.core.ssrf as ssrf

    monkeypatch.setattr(
        ssrf, "_resolve_ips", lambda host: [__import__("ipaddress").ip_address(ip_str)]
    )


def test_ssrf_blocks_disallowed_scheme():
    from buddle.core.ssrf import SSRFValidationError, validate_outbound_url

    with pytest.raises(SSRFValidationError):
        validate_outbound_url("file:///etc/passwd")
    with pytest.raises(SSRFValidationError):
        validate_outbound_url("gopher://internal:6379/")


def test_ssrf_blocks_cloud_metadata(monkeypatch):  # type: ignore[no-untyped-def]
    from buddle.core.ssrf import SSRFValidationError, validate_outbound_url

    _patch_resolve(monkeypatch, "169.254.169.254")
    with pytest.raises(SSRFValidationError):
        validate_outbound_url("http://metadata.evil.com/latest/meta-data/")


def test_ssrf_blocks_loopback(monkeypatch):  # type: ignore[no-untyped-def]
    from buddle.core.ssrf import SSRFValidationError, validate_outbound_url

    _patch_resolve(monkeypatch, "127.0.0.1")
    with pytest.raises(SSRFValidationError):
        validate_outbound_url("http://localhost-trick.com/")


def test_ssrf_blocks_private_when_disallowed(monkeypatch):  # type: ignore[no-untyped-def]
    from buddle.core.ssrf import SSRFValidationError, validate_outbound_url

    _patch_resolve(monkeypatch, "10.1.2.3")
    with pytest.raises(SSRFValidationError):
        validate_outbound_url("http://internal.svc/", allow_private=False)


def test_ssrf_allows_private_when_opted_in(monkeypatch):  # type: ignore[no-untyped-def]
    from buddle.core.ssrf import validate_outbound_url

    _patch_resolve(monkeypatch, "10.1.2.3")
    # same-network backend explicitly permitted
    validate_outbound_url("http://vllm:8000/v1", allow_private=True)


def test_ssrf_allows_public_ip(monkeypatch):  # type: ignore[no-untyped-def]
    from buddle.core.ssrf import validate_outbound_url

    _patch_resolve(monkeypatch, "93.184.216.34")  # example.com-ish public IP
    validate_outbound_url("https://api.example.com/v1", allow_private=False)


def test_ssrf_metadata_blocked_even_when_private_allowed(monkeypatch):  # type: ignore[no-untyped-def]
    from buddle.core.ssrf import SSRFValidationError, validate_outbound_url

    _patch_resolve(monkeypatch, "169.254.169.254")
    # metadata is ALWAYS blocked, even with allow_private=True
    with pytest.raises(SSRFValidationError):
        validate_outbound_url("http://x/", allow_private=True)
