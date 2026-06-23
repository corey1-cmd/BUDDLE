"""Structured logging via structlog. JSON-formatted in non-dev."""

from __future__ import annotations

import logging
import sys
from typing import Any

import structlog

from buddle.config import get_settings


def configure_logging() -> None:
    """Configure structlog + stdlib logging.

    - Dev: pretty console renderer
    - Non-dev: JSON renderer (machine-parseable)
    """
    settings = get_settings()
    level = getattr(logging, settings.log_level.upper(), logging.INFO)

    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=level,
    )

    shared_processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    if settings.is_dev:
        renderer: Any = structlog.dev.ConsoleRenderer(colors=True)
    else:
        renderer = structlog.processors.JSONRenderer()

    structlog.configure(
        processors=[*shared_processors, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Get a structlog logger bound with optional name."""
    logger = structlog.get_logger(name) if name else structlog.get_logger()
    return logger  # type: ignore[no-any-return]
