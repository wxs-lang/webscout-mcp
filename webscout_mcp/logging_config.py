"""Structured logging configuration for webscout-mcp.

Usage::

    from webscout_mcp.logging_config import get_logger, setup_logging
    setup_logging(level="INFO")
    log = get_logger(__name__)
    log.info("fetching url", url="https://example.com", status=200)

Logs are written to stderr in a compact, human-readable format by default.
Set ``WEBSCOUT_LOG_LEVEL=DEBUG`` for verbose output, or
``WEBSCOUT_LOG_JSON=1`` for JSON-formatted logs (useful for log aggregation).
"""

from __future__ import annotations

import logging
import os
import sys
from typing import Any

_LOGGER_NAME = "webscout"
_initialised = False


class StructuredLogger(logging.Logger):
    """Logger that supports structured logging with arbitrary keyword arguments.

    Standard Python logging only accepts specific kwargs (exc_info, extra, etc.).
    This logger automatically wraps arbitrary kwargs into the ``extra`` dict,
    allowing calls like:
        log.info("fetching url", url="https://example.com", status=200)

    The extra fields are then picked up by the custom formatters.
    """

    def _log_with_extra(self, level: int, msg: Any, args: tuple, kwargs: dict) -> None:
        """Extract arbitrary kwargs and merge them into extra."""
        # Standard logging kwargs that should be passed through directly
        standard_kwargs = {"exc_info", "stack_info", "stacklevel", "extra"}
        extra = dict(kwargs.pop("extra", {}) or {})

        # All other kwargs become structured log fields
        for key, value in list(kwargs.items()):
            if key not in standard_kwargs:
                extra[key] = kwargs.pop(key)

        if extra:
            kwargs["extra"] = extra

        super().log(level, msg, *args, **kwargs)

    def debug(self, msg: Any, *args: Any, **kwargs: Any) -> None:
        if self.isEnabledFor(logging.DEBUG):
            self._log_with_extra(logging.DEBUG, msg, args, kwargs)

    def info(self, msg: Any, *args: Any, **kwargs: Any) -> None:
        if self.isEnabledFor(logging.INFO):
            self._log_with_extra(logging.INFO, msg, args, kwargs)

    def warning(self, msg: Any, *args: Any, **kwargs: Any) -> None:
        if self.isEnabledFor(logging.WARNING):
            self._log_with_extra(logging.WARNING, msg, args, kwargs)

    def error(self, msg: Any, *args: Any, **kwargs: Any) -> None:
        if self.isEnabledFor(logging.ERROR):
            self._log_with_extra(logging.ERROR, msg, args, kwargs)

    def critical(self, msg: Any, *args: Any, **kwargs: Any) -> None:
        if self.isEnabledFor(logging.CRITICAL):
            self._log_with_extra(logging.CRITICAL, msg, args, kwargs)

    def exception(self, msg: Any, *args: Any, **kwargs: Any) -> None:
        kwargs["exc_info"] = True
        self.error(msg, *args, **kwargs)


# Register our custom logger class
logging.setLoggerClass(StructuredLogger)


class _ContextFilter(logging.Filter):
    """Inject default fields into every log record."""

    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "component"):
            record.component = record.name.replace(_LOGGER_NAME + ".", "")
        return True


class _JsonFormatter(logging.Formatter):
    """Compact JSON log formatter."""

    def format(self, record: logging.LogRecord) -> str:
        import json

        data: dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "component": getattr(record, "component", record.name),
            "msg": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key not in (
                "name",
                "msg",
                "args",
                "levelname",
                "levelno",
                "pathname",
                "filename",
                "module",
                "exc_info",
                "exc_text",
                "stack_info",
                "lineno",
                "funcName",
                "created",
                "msecs",
                "relativeCreated",
                "thread",
                "threadName",
                "processName",
                "process",
                "message",
                "component",
                "asctime",
                "taskName",
            ):
                data[key] = value
        if record.exc_info:
            data["exc"] = self.formatException(record.exc_info)
        return json.dumps(data, ensure_ascii=False, default=str)


class _ConsoleFormatter(logging.Formatter):
    """Readable one-line console formatter with optional key=value extras."""

    COLORS = {
        "DEBUG": "\033[36m",
        "INFO": "\033[32m",
        "WARNING": "\033[33m",
        "ERROR": "\033[31m",
        "CRITICAL": "\033[35m",
    }
    RESET = "\033[0m"

    def __init__(self, use_color: bool = True) -> None:
        super().__init__()
        self.use_color = use_color and sys.stderr.isatty()

    def format(self, record: logging.LogRecord) -> str:
        level = record.levelname
        if self.use_color:
            level = f"{self.COLORS.get(record.levelname, '')}{level}{self.RESET}"
        ts = self.formatTime(record, "%H:%M:%S")
        component = getattr(record, "component", record.name)
        base = f"{ts} {level:<8} {component:<14} {record.getMessage()}"
        extras: list[str] = []
        for key, value in record.__dict__.items():
            if key not in (
                "name",
                "msg",
                "args",
                "levelname",
                "levelno",
                "pathname",
                "filename",
                "module",
                "exc_info",
                "exc_text",
                "stack_info",
                "lineno",
                "funcName",
                "created",
                "msecs",
                "relativeCreated",
                "thread",
                "threadName",
                "processName",
                "process",
                "message",
                "component",
                "asctime",
                "taskName",
            ):
                extras.append(f"{key}={value}")
        if extras:
            base += "  " + " ".join(extras)
        if record.exc_info:
            base += "\n" + self.formatException(record.exc_info)
        return base


def setup_logging(
    level: str | int | None = None,
    json_format: bool | None = None,
) -> None:
    """Initialise the webscout logger."""
    global _initialised
    if level is None:
        level = os.environ.get("WEBSCOUT_LOG_LEVEL", "WARNING").upper()
    if json_format is None:
        json_format = os.environ.get("WEBSCOUT_LOG_JSON", "").lower() in ("1", "true", "yes")
    root = logging.getLogger(_LOGGER_NAME)
    root.setLevel(level if isinstance(level, int) else getattr(logging, level, logging.WARNING))
    root.propagate = False
    for handler in list(root.handlers):
        root.removeHandler(handler)
    handler = logging.StreamHandler(sys.stderr)
    handler.addFilter(_ContextFilter())
    if json_format:
        handler.setFormatter(_JsonFormatter())
    else:
        handler.setFormatter(_ConsoleFormatter())
    root.addHandler(handler)
    _initialised = True


def get_logger(name: str | None = None) -> logging.Logger:
    """Return a child logger under the ``webscout`` namespace."""
    if not _initialised:
        setup_logging()
    if name is None or name == "__main__":
        return logging.getLogger(_LOGGER_NAME)
    return logging.getLogger(f"{_LOGGER_NAME}.{name}")
