"""FastAPI application entry point."""

from __future__ import annotations

import time
import uuid

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from sqlalchemy import text
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from buddle.api.errors import register_exception_handlers
from buddle.api.v1 import api_v1_router
from buddle.config import get_settings
from buddle.core import metrics
from buddle.core.body_limit import BodySizeLimitMiddleware
from buddle.core.logging import configure_logging, get_logger
from buddle.core.security_headers import SecurityHeadersMiddleware
from buddle.db.session import engine
from buddle.lifespan import lifespan

configure_logging()
log = get_logger(__name__)


def _route_label(request: Request) -> str:
    """Use the matched route template (not the raw path) to keep metric
    cardinality bounded — '/v1/posts/{post_id}' not '/v1/posts/<uuid>'."""
    route = request.scope.get("route")
    return getattr(route, "path", request.url.path)


class RequestIdMiddleware(BaseHTTPMiddleware):
    """Attach X-Request-Id, log the request, and record HTTP metrics."""

    # One-shot proxy-chain diagnostic: logged on the first real request so
    # operators get a measured trusted_proxy recommendation without guessing.
    _proxy_diag_done = False

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = request.headers.get("X-Request-Id") or str(uuid.uuid4())
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)

        if not RequestIdMiddleware._proxy_diag_done:
            RequestIdMiddleware._proxy_diag_done = True
            try:
                from buddle.core.client_ip import diagnose_proxy_chain

                settings = get_settings()
                diag = diagnose_proxy_chain(
                    peer=request.client.host if request.client else None,
                    xff=request.headers.get("x-forwarded-for"),
                    trusted_cidrs=settings.trusted_proxy_cidrs,
                )
                log.info("trusted_proxy.diagnostic", mode=settings.trusted_proxy_mode, **diag)
            except Exception as e:  # diagnostics must never break a request
                log.warning("trusted_proxy.diagnostic_failed", error=str(e))

        start = time.perf_counter()
        response = await call_next(request)
        duration_s = time.perf_counter() - start

        response.headers["X-Request-Id"] = request_id

        label = _route_label(request)
        metrics.http_requests_total.labels(
            method=request.method, path=label, status=str(response.status_code)
        ).inc()
        metrics.http_request_duration.labels(method=request.method, path=label).observe(duration_s)

        log.info(
            "http.request",
            method=request.method,
            path=request.url.path,
            status=response.status_code,
            duration_ms=round(duration_s * 1000, 2),
        )
        return response


def create_app() -> FastAPI:
    settings = get_settings()

    # ── Sentry (optional): only touched when a DSN is configured. The SDK is
    # an optional dependency (`pip install -e ".[observability]"`); missing
    # package + configured DSN logs a warning instead of crashing the app.
    if settings.sentry_dsn:
        try:
            import sentry_sdk

            sentry_sdk.init(
                dsn=settings.sentry_dsn,
                environment=settings.app_env,
                release=f"{settings.app_name}@{settings.app_version}",
                traces_sample_rate=settings.sentry_traces_sample_rate,
                # 원문 비노출 원칙: 요청 본문/PII를 이벤트에 싣지 않는다.
                send_default_pii=False,
                max_request_body_size="never",
            )
            log.info("sentry.initialised", env=settings.app_env)
        except ImportError:
            log.warning("sentry.dsn_set_but_sdk_missing", hint='pip install -e ".[observability]"')

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        lifespan=lifespan,
        docs_url="/docs" if settings.is_dev else None,
        redoc_url="/redoc" if settings.is_dev else None,
    )

    # Order matters: CORS outermost, then security headers, then request id.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-Id"],
    )
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(RequestIdMiddleware)
    # Body cap is the outermost custom layer: reject oversize payloads before
    # any downstream work (added last → runs first in Starlette's stack).
    app.add_middleware(BodySizeLimitMiddleware, max_body_bytes=settings.max_request_body_bytes)

    register_exception_handlers(app)
    app.include_router(api_v1_router)

    # ── Liveness: process is up (no dependency checks) ──
    @app.get("/health", tags=["meta"])
    async def health() -> dict[str, str]:
        return {"status": "ok", "version": settings.app_version}

    # ── Readiness: dependencies reachable (DB + Redis) ──
    @app.get("/ready", tags=["meta"])
    async def ready(request: Request) -> Response:
        checks: dict[str, str] = {}
        ok = True

        try:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            checks["postgres"] = "ok"
        except Exception as e:
            checks["postgres"] = f"error: {e}"
            ok = False

        redis = getattr(request.app.state, "redis", None)
        if redis is None:
            checks["redis"] = "not_configured"
            ok = False
        else:
            try:
                await redis.ping()
                checks["redis"] = "ok"
            except Exception as e:
                checks["redis"] = f"error: {e}"
                ok = False

        import json

        payload = json.dumps({"ready": ok, "checks": checks})
        return Response(
            content=payload,
            media_type="application/json",
            status_code=200 if ok else 503,
        )

    # ── Metrics (Prometheus) ──
    @app.get("/metrics", tags=["meta"], include_in_schema=False)
    async def prometheus_metrics() -> Response:
        payload, content_type = metrics.render_latest()
        return Response(content=payload, media_type=content_type)

    @app.get("/api", include_in_schema=False)
    async def api_root() -> dict[str, str]:
        return {"name": settings.app_name, "version": settings.app_version}

    # ── Frontend: serve the web/ prototype as static files at root ───────────
    # Lets the whole app run from one origin (http://localhost:8000) — no CORS
    # or BUDDLE_API_BASE wiring needed. The directory is optional: if web/ is
    # absent (e.g. a pure-API deploy), the JSON root above still answers at /api.
    import mimetypes
    import pathlib

    from fastapi.staticfiles import StaticFiles

    # Slim base images (python:*-slim) ship without /etc/mime.types, so
    # mimetypes.guess_type() returns None for .css/.js and StaticFiles falls
    # back to text/plain. With our `X-Content-Type-Options: nosniff` header the
    # browser then REFUSES to apply the stylesheet/scripts → a fully unstyled
    # page. Register the types explicitly so serving is correct on any image.
    for _ext, _type in (
        (".css", "text/css"),
        (".js", "text/javascript"),
        (".mjs", "text/javascript"),
        (".woff2", "font/woff2"),
        (".svg", "image/svg+xml"),
        (".json", "application/json"),
        (".webmanifest", "application/manifest+json"),
    ):
        mimetypes.add_type(_type, _ext)

    class _NoStaleStatic(StaticFiles):
        """StaticFiles that forces revalidation on every asset.

        Without an explicit Cache-Control, browsers apply heuristic caching and
        can keep serving a stale copy — including a broken/empty body captured
        while an earlier deploy was failing — so the page renders unstyled even
        after a fix ships. ``no-cache`` means "revalidate before use": the
        browser still caches, but always checks the ETag, so a corrected file
        is picked up immediately and a stale broken one is never reused.
        """

        async def get_response(self, path: str, scope):  # type: ignore[no-untyped-def]
            response = await super().get_response(path, scope)
            response.headers.setdefault("Cache-Control", "no-cache")
            return response

    _web_dir = pathlib.Path(__file__).resolve().parents[2] / "web"
    if _web_dir.is_dir():
        # html=True → "/" serves web/login.html-style index; unknown paths 404.
        app.mount("/", _NoStaleStatic(directory=str(_web_dir), html=True), name="web")
    else:

        @app.get("/", include_in_schema=False)
        async def root() -> dict[str, str]:
            return {"name": settings.app_name, "version": settings.app_version}

    return app


app = create_app()
