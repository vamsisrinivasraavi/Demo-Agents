"""
Structured logging configuration.

- Development: human-readable colored output
- Production: JSON-formatted logs (for ELK / CloudWatch / Datadog)
- Request-scoped correlation IDs via contextvars
- Performance timing helper for critical paths
"""

import logging
import sys
import time
from contextvars import ContextVar
from functools import wraps
from typing import Any, Callable
from uuid import uuid4

import structlog

from app.core.config import get_settings

# Context variable for per-request correlation ID
correlation_id_var: ContextVar[str] = ContextVar("correlation_id", default="")


def get_correlation_id() -> str:
    """Get current request's correlation ID."""
    return correlation_id_var.get()


def set_correlation_id(cid: str | None = None) -> str:
    """Set correlation ID for current context. Generates one if not provided."""
    cid = cid or uuid4().hex[:12]
    correlation_id_var.set(cid)
    return cid


def add_correlation_id(
    logger: logging.Logger, method_name: str, event_dict: dict[str, Any]
) -> dict[str, Any]:
    """Structlog processor: inject correlation_id into every log entry."""
    cid = correlation_id_var.get()
    if cid:
        event_dict["correlation_id"] = cid
    return event_dict


def setup_logging() -> None:
    """
    Configure structlog + stdlib logging.
    Call once at application startup (in main.py lifespan).
    """
    settings = get_settings()
    is_production = settings.ENVIRONMENT == "production"

    # Shared processors for both dev and prod
    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        add_correlation_id,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.UnicodeDecoder(),
    ]

    if is_production:
        # JSON output for log aggregation systems
        shared_processors.append(structlog.processors.format_exc_info)
        renderer = structlog.processors.JSONRenderer()
    else:
        # Pretty console output for development
        renderer = structlog.dev.ConsoleRenderer(colors=True)

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    # Configure stdlib root logger
    formatter = structlog.stdlib.ProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(getattr(logging, settings.LOG_LEVEL))

    # Quiet noisy third-party loggers
    for noisy in ("uvicorn.access", "httpcore", "httpx", "motor"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Get a named logger instance. Use module __name__ as convention."""
    return structlog.get_logger(name)


# ──────────────────────────────────────────────
# Performance Timing Decorator
# ──────────────────────────────────────────────


def log_duration(operation: str) -> Callable:
    """
    Decorator that logs execution time of async functions.
    Usage:
        @log_duration("qdrant_search")
        async def search_vectors(...):
    """
    def decorator(func: Callable) -> Callable:
        logger = get_logger(func.__module__)

        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            start = time.perf_counter()
            try:
                result = await func(*args, **kwargs)
                elapsed_ms = (time.perf_counter() - start) * 1000
                logger.info(
                    "operation.completed",
                    operation=operation,
                    duration_ms=round(elapsed_ms, 2),
                )
                return result
            except Exception as exc:
                elapsed_ms = (time.perf_counter() - start) * 1000
                logger.error(
                    "operation.failed",
                    operation=operation,
                    duration_ms=round(elapsed_ms, 2),
                    error=str(exc),
                )
                raise

        return wrapper
    return decorator