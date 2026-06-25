"""Security response headers middleware.

API 응답(JSON)과 정적 HTML 파일에 각기 다른 헤더를 적용합니다.
- JSON/API: 극도로 제한적인 CSP (default-src 'none')
- HTML 정적 파일: 인라인 스크립트·스타일·Google Fonts·CDN을 허용하는 실용적 CSP
"""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

# ── JSON / API 전용 (기본값: 모두 차단) ─────────────────────────────────
_API_HEADERS: dict[str, str] = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-site",
    "Permissions-Policy": "geolocation=(), microphone=(), camera=()",
    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
}

# ── HTML 정적 파일 전용 ───────────────────────────────────────────────────
# NOTE(future hardening): script-src/style-src 아래 'unsafe-inline'은 정적 HTML이
# 인라인 <script>/<style>를 쓰기 때문에 현재 불가피하다. XSS 방어를 강화하려면
# per-request nonce(CSP nonce-...)로 전환해야 하는데, 이는 모든 정적 페이지를
# 템플릿 렌더링으로 바꿔 요청마다 nonce를 주입해야 하므로 별도 작업으로 분리한다.
_HTML_CSP = (
    "default-src 'self'; "
    # 인라인 <style> 및 외부 Google Fonts 허용
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
    # Google Fonts 웹폰트 파일
    "font-src 'self' https://fonts.gstatic.com; "
    # 이미지: 자체 + data URI + 외부 HTTPS
    "img-src 'self' data: https:; "
    # 인라인 <script> + jsDelivr CDN (Chart.js 등)
    "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
    # API 호출 + WebSocket
    "connect-src 'self' ws: wss:; "
    # 동일 출처 iframe 허용 (같은 앱 내 embed 등)
    "frame-ancestors 'self'; "
    "base-uri 'self'; "
    "form-action 'self'; "
    "object-src 'none'"
)

_HTML_HEADERS: dict[str, str] = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "SAMEORIGIN",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Cross-Origin-Opener-Policy": "same-origin",
    # API와 마찬가지로 CORP를 명시해 교차 출처 임베드를 제한한다(이전엔 누락).
    # 같은 앱 내(동일 출처) 로드만 허용.
    "Cross-Origin-Resource-Policy": "same-origin",
    "Permissions-Policy": "geolocation=(), microphone=(), camera=()",
    "Content-Security-Policy": _HTML_CSP,
}


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)

        # Content-Type으로 HTML 여부 판별
        ct = response.headers.get("content-type", "")
        headers = _HTML_HEADERS if "text/html" in ct else _API_HEADERS

        for key, value in headers.items():
            response.headers.setdefault(key, value)

        # HSTS는 HTTPS에서만 (로컬 http 개발 환경 깨지지 않도록)
        if request.url.scheme == "https":
            response.headers.setdefault(
                "Strict-Transport-Security",
                "max-age=31536000; includeSubDomains",
            )

        return response
