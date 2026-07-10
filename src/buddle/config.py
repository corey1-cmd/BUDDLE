"""Application settings, loaded from .env via pydantic-settings."""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

# Sentinel dev-only secrets. If any of these is still in use when APP_ENV is
# 'production', startup fails fast (see _reject_dev_secrets_in_prod). Keeping
# them as named constants lets the validator detect "still default" reliably.
_DEV_JWT_SECRET = "dev_only_change_in_production_______"
_DEV_INTEGRITY_KEY = "dev_integrity_key_change_in_production_____"


class Settings(BaseSettings):
    """Singleton settings instance."""

    # ── App
    app_env: Literal["development", "staging", "production"] = "development"
    app_name: str = "buddle"
    app_version: str = "0.1.0"
    log_level: str = "INFO"

    # ── Server
    host: str = "0.0.0.0"
    port: int = 8000

    # ── DB
    database_url: str = Field(
        default="postgresql+asyncpg://buddle:change_me@localhost:5432/buddle_dev"
    )
    # Connection pool sizing. Conservative defaults suit a managed pooler
    # (Supabase Supavisor / pgbouncer) and free-tier connection limits — the
    # pooler does the heavy multiplexing, so a large app-side pool is wasteful
    # and can exhaust the tenant's connection quota.
    db_pool_size: int = 5
    db_max_overflow: int = 10
    db_pool_recycle_s: int = 1800
    # asyncpg client-side prepared-statement cache. MUST be 0 behind a
    # transaction-mode pooler (Supabase Supavisor / pgbouncer), otherwise queries
    # fail with "prepared statement __asyncpg__ already exists". 0 is safe
    # everywhere (direct Postgres included); raise it only for a dedicated,
    # non-pooled connection if you need the micro-optimisation.
    db_statement_cache_size: int = 0

    # ── Redis
    redis_url: str = Field(default="redis://localhost:6379/0")

    # ── JWT
    jwt_secret_key: SecretStr = Field(default=SecretStr(_DEV_JWT_SECRET))
    jwt_algorithm: str = "HS256"
    jwt_access_expire_min: int = 15
    jwt_refresh_expire_days: int = 30
    # Short overlap window (seconds) during which a just-rotated refresh token
    # is still accepted, to tolerate concurrent refreshes from the same client
    # (e.g. a mobile app retrying). Reuse beyond this window = theft -> family
    # revocation. Set to 0 to disable the grace period (strict rotation).
    refresh_grace_period_seconds: int = 10

    # ── In-app scheduler (knowledge/plaza standby ticks)
    # Off by default: tests and one-shot tooling should not spawn background
    # loops. Production/compose turns it on via SCHEDULER_ENABLED=true. The
    # admin endpoints (/v1/admin/*/tick) keep working either way, so external
    # cron remains a valid alternative.
    scheduler_enabled: bool = False
    knowledge_tick_interval_s: int = 300
    plaza_tick_interval_s: int = 180
    # News ingestion cadence. 1시간 주기 — 피드 화제 업데이트엔 이 정도면
    # 충분하다는 운영 판단(2분 실험 후 조정). seen-set/SimHash/guid UNIQUE
    # 3중 중복 제거가 재수집을 전량 흡수한다.
    # Set to 0 to disable; requires SCHEDULER_ENABLED=true to run automatically.
    news_tick_interval_s: int = 3600
    # 해외 RSS 한국어 배치 번역(틱당 1~2회 호출, 기사당 아님) — 실패 시 원문
    # 공개(fail-open). 끄면 해외 기사가 원문(영문)으로 공개된다.
    news_translate_foreign: bool = True
    # Minimum relevance score (0-1) for an article to be stored after AI analysis.
    news_relevance_threshold: float = 0.3
    # Per-article LLM analysis in the news pipeline. Default OFF: it made one
    # AI call per fetched article (60건 수집 = 60+회 → 무료 쿼터 소진·429 폭주).
    # The default algorithmic path (ai/news/topics.py) needs zero API calls.
    news_ai_analysis_enabled: bool = False

    # ── Observability: Sentry (optional)
    # No DSN (default) -> never imported/initialised; zero overhead.
    sentry_dsn: str | None = None
    sentry_traces_sample_rate: float = 0.1

    # ── Persona affect-aware dialogue (evidence-based, bias-safe)
    # Reads only the current message (no profiling/history adaptation) to add a
    # response-posture hint (ACR / validation / active listening) so personas
    # converse more warmly. Toggle off to disable.
    affect_guidance_enabled: bool = True

    # ── Persona EKB cognitive pipeline (information processing + decision)
    # Supersedes affect_guidance when enabled: runs the full staged analysis
    # and injects a compact guidance block. Still zero extra LLM calls.
    cognition_enabled: bool = True

    # ── Persona long-term memory (LTM)
    # Persists the EKB Retention stage (PersonaMemory) and serves the EKB
    # Search stage: recall = recency·importance·relevance (Park et al. 2023),
    # reinforcement on retrieval (ACT-R), capacity-bounded forgetting.
    memory_enabled: bool = True
    memory_recall_k: int = 4
    memory_max_per_persona: int = 500

    # ── User profiling (OCEAN soft estimates, connection-only)
    # 관찰: 대화(특질 신호) + 게시(관심 센트로이드, 기존 임베딩 재사용).
    # 주권: opt-out 시 관찰 중단, 사용자 수정 시 자동 갱신 동결(§10-1).
    profile_enabled: bool = True

    # ── Conversation psychology (Social Penetration + Gottman + 10 principles)
    # 페르소나 대화에 관계 레벨(SPT 5단계)·정서은행계좌 점수(Gottman 5:1)·대화 분위기·
    # 10가지 대화 원칙을 적용. 끄면 기존 EKB 대화로 폴백.
    conversation_enabled: bool = True

    # ── Argument mining / debate dashboard (Toulmin reduced)
    # 게시 시 주장·근거·반박·질문을 추출(Stab & Gurevych 2017 축약)하고 화제별로
    # 군집화해 토론 대시보드(/v1/topics/{tag}/debate)로 정리. 끄면 추출 안 함.
    argument_enabled: bool = True

    # ── Persona quota policy
    free_persona_quota: int = 3
    plus_persona_quota: int = 10
    pro_persona_quota: int = 999

    # ── Persona inference endpoint (OpenAI-compat; used by mediator AI analysis)
    # Shared with the seed_persona_models script. Set via env vars.
    persona_endpoint_url: str = ""
    persona_endpoint_api_key: str = ""
    persona_model: str = (
        "gemini-2.5-flash"  # 2.0-flash 무료 티어 폐지(limit 0); 2.5-flash는 무료 작동
    )

    # ── Embeddings (mediator content similarity)
    # BGE-M3 (1024-dim, multilingual SOTA) is the matching model; EMBED_DIM=1024
    # and migration 0016 align the pgvector columns. ko-sroberta (768) remains a
    # fallback (would require EMBED_DIM=768 + reverting 0016).
    embedding_provider: Literal["stub", "sentence_transformers", "vllm_endpoint"] = "stub"
    embedding_model_id: str = "BAAI/bge-m3"
    embedding_endpoint_url: str = ""
    embedding_device: str = "cpu"

    # ── Ethics (leukocyte AI)
    ethics_provider: Literal["stub", "local_hf", "vllm_endpoint", "llama_guard"] = "stub"
    ethics_model_id: str = ""
    ethics_endpoint_url: str = ""

    # ── 유의 단어 잡지 (백혈구 AI 7단계 추론 게이트)
    # 경로를 설정하면 활성화. JSON 파일의 version 필드가 바뀌면 자동 리로드.
    # 미설정(None) = 게이트 비활성 (conscience.py 단순 게이트만 작동).
    # 예: CAUTION_LEXICON_PATH=src/buddle/data/caution_lexicon.json
    caution_lexicon_path: str | None = None

    # Multilingual pipeline (Korean/English first). The translator turns a
    # persona's thought into target-language versions; stub round-trips for
    # dev/tests, llm_endpoint uses a chat model preserving voice.
    # Model: GLM-4.6 (MIT) — officially tuned for Korean + social + creative.
    translation_provider: Literal["stub", "llm_endpoint"] = "stub"
    translation_model_id: str = "glm-4.6"
    translation_endpoint_url: str = ""

    # Knowledge synthesis (Layer B integration). Recombines knowledge units into
    # insight bundles; stub is deterministic (no LLM), llm_endpoint uses a chat
    # model that presents perspectives rather than asserting conclusions.
    # Model: GLM-4.6 (workhorse). Deep tier may use GLM-5.1 (754B) when a
    # dedicated reasoning endpoint is available (set synthesis_endpoint_url).
    synthesis_provider: Literal["stub", "llm_endpoint"] = "stub"
    synthesis_model_id: str = "glm-4.6"
    synthesis_endpoint_url: str = ""
    # Severity at/above which content is auto-hidden from public distribution
    # (still stored; just suppressed). low|mid|high.
    ethics_block_severity: Literal["low", "mid", "high"] = "high"
    # Per-category 0-7 severity threshold at/above which a post is ALWAYS
    # suppressed regardless of the bucket policy above. Lets the most serious
    # MLCommons categories (child exploitation, weapons, violent/sex crimes,
    # self-harm) be blocked at a lower bar than generic content. Categories not
    # listed fall back to the bucket policy. Keys are hazard codes (S1..S13).
    ethics_category_block_levels: dict[str, int] = Field(
        default_factory=lambda: {
            "S4": 1,  # child sexual exploitation — block at any signal
            "S9": 4,  # indiscriminate weapons (CBRN)
            "S1": 5,  # violent crimes
            "S3": 5,  # sex-related crimes
            "S11": 5,  # suicide & self-harm
        }
    )

    # ── Importance function (additive + tanh normalization)
    importance_i_max: float = 1.0
    importance_kappa: float = 50.0
    # Signed contribution deltas per event type
    importance_delta_mention: float = 1.0
    importance_delta_like: float = 2.0
    importance_delta_report: float = -5.0
    importance_delta_ethics_low: float = -2.0
    importance_delta_ethics_mid: float = -5.0
    importance_delta_ethics_high: float = -15.0

    # ── Feed ranking weights
    feed_recency_half_life_hours: float = 24.0
    feed_w_importance: float = 0.5
    feed_w_recency: float = 0.5

    # ── Central Manager AI: monitoring + SLO + engagement
    # Idle gap after which a user session is considered ended (minutes).
    session_idle_timeout_min: int = 30
    # SLO targets for the golden-signals health verdict.
    slo_error_rate_warn: float = 0.02  # 2% error rate -> warn
    slo_error_rate_critical: float = 0.05  # 5% -> critical
    slo_latency_p95_warn_ms: float = 800.0
    slo_latency_p95_critical_ms: float = 2000.0
    # Open ethics alerts above these counts escalate the health verdict.
    health_open_alerts_warn: int = 5
    health_open_alerts_critical: int = 20
    # Recent-window length for engagement/growth metrics (days).
    engagement_window_days: int = 7

    # ── Technician AI: integrity + dynamic authority
    # Dedicated key for the transformation-log HMAC chain. MUST differ from
    # jwt_secret_key and be stored in a separate secret in production.
    integrity_hmac_key: SecretStr = Field(default=SecretStr(_DEV_INTEGRITY_KEY))
    # Authority token economics. Central manager starts with base authority;
    # each UNVERIFIED transformation it (or an impostor) makes debits it, each
    # technician-verified restoration credits the technician. When the
    # technician's authority exceeds the central manager's, the system flips to
    # TECH_ELEVATED (the self-healing override).
    authority_central_base: float = 100.0
    authority_technician_base: float = 0.0
    # Per-event authority deltas
    authority_debit_unverified: float = 10.0  # central loses this per unverified change
    authority_credit_restoration: float = 10.0  # technician gains this per verified restore
    # Magnitude (per transformation) above which a change REQUIRES a valid
    # justification signature, else it is treated as unverified/suspicious.
    authority_high_magnitude_threshold: float = 5.0

    # ── CORS
    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:3000"]
    )

    # ── Trusted reverse-proxy handling (X-Forwarded-For)
    # The client IP used by the rate limiter must NOT be taken from the first
    # XFF entry blindly — any client can set that header and rotate it to
    # bypass IP-based limits. Three strategies, chosen by trusted_proxy_mode:
    #
    #   "auto"   (default) → "cidr" if trusted_proxy_cidrs is set, else "hops"
    #                        if trusted_proxy_hops > 0, else "socket".
    #   "socket"           → ignore XFF entirely, use the socket peer (correct
    #                        when the app is directly exposed).
    #   "cidr"             → walk XFF from the right, discard hops inside
    #                        trusted_proxy_cidrs, first untrusted = client.
    #                        Auto-adapts to any number of proxies (recommended).
    #   "hops"             → trust the rightmost trusted_proxy_hops entries.
    #                        Range-checked against the real chain length.
    trusted_proxy_mode: Literal["auto", "socket", "cidr", "hops"] = "auto"
    # Private/infra ranges that front the app (comma-separated CIDRs). Defaults
    # cover the standard private IPv4 blocks + loopback + IPv6 ULA/loopback, so
    # "cidr" mode works out-of-the-box for the common case of proxies on a
    # private network. Tighten to your actual proxy subnet in production.
    trusted_proxy_cidrs: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: [
            "10.0.0.0/8",
            "172.16.0.0/12",
            "192.168.0.0/16",
            "127.0.0.0/8",
            "::1/128",
            "fc00::/7",
        ]
    )
    # Fallback when ranges can't be enumerated: number of proxies in front of
    # the app. Bounded to [0, 8] — more than a handful of hops is almost
    # certainly a misconfiguration, and an unbounded value would be a footgun.
    trusted_proxy_hops: int = Field(default=0, ge=0, le=8)

    # ── Request body hard cap (bytes). Oversized bodies are rejected with 413
    # before the route/parser runs, bounding memory-amplification DoS. Auth and
    # post/comment payloads are small; 256 KiB is generous.
    max_request_body_bytes: int = 262_144

    # ── WebSocket CSWSH guard
    # Browsers don't apply CORS to WebSocket upgrades, so a cross-origin page
    # could open a socket with the victim's cookies. We authenticate via an
    # in-band token (not cookies), which already blocks the classic attack, but
    # we additionally check the Origin header against this allowlist. Empty list
    # falls back to cors_origins. Non-browser clients (no Origin header) are
    # allowed only when ws_allow_missing_origin is true (native apps/tests).
    ws_allowed_origins: Annotated[list[str], NoDecode] = Field(default_factory=list)
    ws_allow_missing_origin: bool = True

    # ── SSRF guard for admin-registered backend URLs
    # Most deployments run the model server inside the same private network
    # (e.g. http://vllm:8000), so private ranges are allowed by default in dev.
    # In production, set this to false unless the backend truly is same-network,
    # and rely on an egress proxy/network policy as the outer layer.
    allow_private_backend_hosts: bool = True

    # ── Rate limiting (defense-in-depth)
    # Layer 2: process-local in-memory backup limiter (works even if Redis is
    # down, bounding single-instance abuse). Independent of the Redis layer.
    ratelimit_local_backup_enabled: bool = True
    ratelimit_local_login_per_min: int = 30  # per-process ceiling for login
    ratelimit_local_default_per_min: int = 300  # per-process ceiling, other auth
    # Layer 3: per-account login lockout (defeats IP-rotating credential
    # stuffing). After N consecutive failures within the window, the account is
    # temporarily locked.
    account_lockout_threshold: int = 10
    account_lockout_window_min: int = 15
    account_lockout_duration_min: int = 15

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @field_validator("cors_origins", "ws_allowed_origins", "trusted_proxy_cidrs", mode="before")
    @classmethod
    def _split_cors(cls, v: str | list[str]) -> list[str]:
        if isinstance(v, str):
            return [origin.strip() for origin in v.split(",") if origin.strip()]
        return v

    @model_validator(mode="after")
    def _reject_dev_secrets_in_prod(self) -> Settings:
        """Fail fast if dev-default secrets are still in use in production.

        Using the shipped default JWT/integrity keys in production would let
        anyone who has read the source forge tokens or chain hashes. We refuse
        to start rather than run insecurely. Also enforces that the two keys
        differ (the integrity chain must not share the JWT key)."""
        if self.app_env == "production":
            problems: list[str] = []
            if self.jwt_secret_key.get_secret_value() == _DEV_JWT_SECRET:
                problems.append("jwt_secret_key is still the dev default")
            if self.integrity_hmac_key.get_secret_value() == _DEV_INTEGRITY_KEY:
                problems.append("integrity_hmac_key is still the dev default")
            if self.jwt_secret_key.get_secret_value() == self.integrity_hmac_key.get_secret_value():
                problems.append("jwt_secret_key and integrity_hmac_key must differ")
            # Quantum note: HS256/HMAC-SHA256 are symmetric, so Grover's
            # algorithm only halves effective strength. A 32-byte (256-bit)
            # secret keeps >=128-bit post-quantum security. We require >=32
            # chars; >=44 (a base64-encoded 32 bytes) is recommended.
            if len(self.jwt_secret_key.get_secret_value()) < 32:
                problems.append(
                    "jwt_secret_key must be at least 32 characters (256-bit; quantum-safe floor)"
                )
            if len(self.integrity_hmac_key.get_secret_value()) < 32:
                problems.append(
                    "integrity_hmac_key must be at least 32 characters (256-bit; quantum-safe floor)"
                )
            # A wildcard CORS origin combined with credentialed requests is a
            # cross-origin data-theft vector; refuse it in production.
            if "*" in self.cors_origins:
                problems.append("cors_origins must not be '*' in production (credentialed CORS)")
            # Proxy-mode consistency: an explicit mode whose backing value is
            # empty would silently fall back to "socket" and ignore XFF — which,
            # behind a real proxy, makes the rate limiter key on the proxy IP
            # (all users share one bucket). Catch the misconfig at boot.
            if self.trusted_proxy_mode == "cidr" and not self.trusted_proxy_cidrs:
                problems.append("trusted_proxy_mode='cidr' requires trusted_proxy_cidrs")
            if self.trusted_proxy_mode == "hops" and self.trusted_proxy_hops <= 0:
                problems.append("trusted_proxy_mode='hops' requires trusted_proxy_hops >= 1")
            if problems:
                raise ValueError(
                    "Insecure production configuration: "
                    + "; ".join(problems)
                    + ". Set strong, distinct secrets via environment variables."
                )
        return self

    @property
    def is_dev(self) -> bool:
        return self.app_env == "development"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached settings accessor. Reset between tests by overriding the cache."""
    return Settings()
