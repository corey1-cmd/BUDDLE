"""Application metrics (Prometheus).

If prometheus_client is installed, real counters/histograms are used and
`/metrics` exposes them. Otherwise a no-op shim keeps call sites working.

Metrics:
  buddle_http_requests_total{method,path,status}
  buddle_http_request_duration_seconds{method,path}
  buddle_persona_inference_total{backend,outcome}    # outcome: ok|fallback|cache_hit
  buddle_post_created_total{visibility}
  buddle_distribution_created_total
"""

from __future__ import annotations

from typing import Any

try:
    from prometheus_client import (
        CONTENT_TYPE_LATEST,
        Counter,
        Histogram,
        generate_latest,
    )

    _PROM_AVAILABLE = True
except ImportError:  # pragma: no cover - exercised only without the dep
    _PROM_AVAILABLE = False
    CONTENT_TYPE_LATEST = "text/plain"


class _NoopMetric:
    def labels(self, *args: Any, **kwargs: Any) -> _NoopMetric:
        return self

    def inc(self, amount: float = 1) -> None:
        return None

    def observe(self, amount: float) -> None:
        return None


if _PROM_AVAILABLE:
    http_requests_total = Counter(
        "buddle_http_requests_total",
        "Total HTTP requests",
        ["method", "path", "status"],
    )
    http_request_duration = Histogram(
        "buddle_http_request_duration_seconds",
        "HTTP request duration",
        ["method", "path"],
    )
    persona_inference_total = Counter(
        "buddle_persona_inference_total",
        "Persona inference calls",
        ["backend", "outcome"],
    )
    post_created_total = Counter(
        "buddle_post_created_total",
        "Posts created",
        ["visibility"],
    )
    distribution_created_total = Counter(
        "buddle_distribution_created_total",
        "Private distributions created",
    )
    scheduler_runs_total = Counter(
        "buddle_scheduler_runs_total",
        "Background scheduler job runs",
        ["job", "outcome"],  # outcome: ok|error|skipped_lock
    )
    scheduler_run_duration = Histogram(
        "buddle_scheduler_run_duration_seconds",
        "Background scheduler job duration",
        ["job"],
    )
else:  # pragma: no cover
    http_requests_total = _NoopMetric()  # type: ignore[assignment]
    http_request_duration = _NoopMetric()  # type: ignore[assignment]
    persona_inference_total = _NoopMetric()  # type: ignore[assignment]
    post_created_total = _NoopMetric()  # type: ignore[assignment]
    distribution_created_total = _NoopMetric()  # type: ignore[assignment]
    scheduler_runs_total = _NoopMetric()  # type: ignore[assignment]
    scheduler_run_duration = _NoopMetric()  # type: ignore[assignment]


def render_latest() -> tuple[bytes, str]:
    """Return (payload, content_type) for the /metrics endpoint."""
    if _PROM_AVAILABLE:
        return generate_latest(), CONTENT_TYPE_LATEST
    return b"# prometheus_client not installed\n", "text/plain"


def is_available() -> bool:
    return _PROM_AVAILABLE
