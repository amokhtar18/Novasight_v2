"""Structured JSON logging with PII redaction.

Configures the stdlib ``logging`` hierarchy once per process (called from the
FastAPI lifespan).  All handlers emit newline-delimited JSON records.  A
``RedactionFilter`` is attached to every handler so that sensitive field values
are never written to any sink — not even to stderr or a log aggregator.

Usage::

    from app.core.logging import configure_logging
    configure_logging(level="INFO")
"""
from __future__ import annotations

import json
import logging
import time
from collections.abc import Mapping
from typing import Any

# Keys whose values must be scrubbed before a record reaches any handler.
_REDACTED_KEYS: frozenset[str] = frozenset(
    {
        "password",
        "token",
        "secret",
        "api_key",
        "apikey",
        "authorization",
        "cookie",
        "email",
        "access_key",
        "secret_key",
    }
)
_REDACTED_PLACEHOLDER = "***"


def _redact(obj: Any, *, _depth: int = 0) -> Any:  # noqa: ANN401
    """Recursively redact sensitive keys from dicts (up to depth 10)."""
    if _depth > 10:  # guard against pathological nesting
        return obj
    if isinstance(obj, Mapping):
        return {
            k: (
                _REDACTED_PLACEHOLDER
                if k.lower() in _REDACTED_KEYS
                else _redact(v, _depth=_depth + 1)
            )
            for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [_redact(item, _depth=_depth + 1) for item in obj]
    return obj


class RedactionFilter(logging.Filter):
    """Scrub sensitive field values from ``LogRecord.msg`` and ``args``."""

    def filter(self, record: logging.LogRecord) -> bool:
        # Redact structured extras stored as a dict on the record.
        if isinstance(record.msg, Mapping):
            record.msg = _redact(record.msg)
        if record.args and isinstance(record.args, Mapping):
            record.args = _redact(record.args)
        return True


class _JsonFormatter(logging.Formatter):
    """Format a ``LogRecord`` as a single-line JSON object."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(record.created)),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        # Include any extra keyword args passed at call-site.
        for key, val in record.__dict__.items():
            if key not in _LOG_RECORD_BUILTIN_ATTRS:
                payload[key] = val
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


# Attributes that are native to LogRecord — we skip them in the extras loop.
_LOG_RECORD_BUILTIN_ATTRS: frozenset[str] = frozenset(
    {
        "args",
        "asctime",
        "created",
        "exc_info",
        "exc_text",
        "filename",
        "funcName",
        "levelname",
        "levelno",
        "lineno",
        "message",
        "module",
        "msecs",
        "msg",
        "name",
        "pathname",
        "process",
        "processName",
        "relativeCreated",
        "stack_info",
        "taskName",
        "thread",
        "threadName",
    }
)


def configure_logging(level: str = "INFO") -> None:
    """Set up the root logger with a JSON handler and the redaction filter.

    Safe to call multiple times (idempotent via ``force=True``).
    """
    redaction_filter = RedactionFilter()
    handler = logging.StreamHandler()
    handler.setFormatter(_JsonFormatter())
    handler.addFilter(redaction_filter)

    logging.basicConfig(
        level=level.upper(),
        handlers=[handler],
        force=True,
    )
    # Quiet noisy third-party loggers.
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
