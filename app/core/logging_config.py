"""Logging configuration.

Console formatting is used for local development; JSON is emitted in deployed
environments so log aggregators can parse call events without regex.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime

_RESERVED_RECORD_KEYS = set(
    logging.LogRecord("", 0, "", 0, "", (), None).__dict__.keys()
) | {"message", "asctime", "taskName"}


class JsonLogFormatter(logging.Formatter):
    """Render log records as single-line JSON, preserving structured extras."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key not in _RESERVED_RECORD_KEYS and not key.startswith("_"):
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


class ConsoleLogFormatter(logging.Formatter):
    """Human-readable formatter that appends structured extras inline."""

    def __init__(self) -> None:
        super().__init__(fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s")

    def format(self, record: logging.LogRecord) -> str:
        base = super().format(record)
        extras = {
            key: value
            for key, value in record.__dict__.items()
            if key not in _RESERVED_RECORD_KEYS and not key.startswith("_")
        }
        if extras:
            rendered = " ".join(f"{key}={value}" for key, value in extras.items())
            return f"{base} | {rendered}"
        return base


def configure_logging(level: str = "INFO", log_format: str = "console") -> None:
    """Install the root logging handler. Safe to call more than once."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonLogFormatter() if log_format == "json" else ConsoleLogFormatter())

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(level.upper())

    # Uvicorn installs its own handlers; route them through ours instead.
    for noisy_logger in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logging.getLogger(noisy_logger).handlers.clear()
        logging.getLogger(noisy_logger).propagate = True
