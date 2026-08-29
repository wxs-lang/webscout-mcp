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


class StructuredLogger:
    """Logger wrapper that supports structured logging with arbitrary keyword arguments.

    This is a wrapper around standard Python logging.Logger, NOT a subclass.
    It does NOT modify global logging behavior (no setLoggerClass call),
    so it won't affect third-party loggers in the same process.

    Standard Python logging only accepts specific kwargs (exc_info, extra, etc.).
    This wrapper automatically wraps arbitrary kwargs into the ``extra`` dict,
    allowing calls like:
        log.info("fetching url", url="https://example.com", status=200)

    The extra fields are then picked up by the custom formatters.
    """

    def __init__(self, logger: logging.Logger) -> None:
        self._logger = logger

    def _process_kwargs(self, kwargs: dict) -> dict:
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

        return kwargs

    def debug(self, msg: Any, *args: Any, **kwargs: Any) -> None:
        if self._logger.isEnabledFor(logging.DEBUG):
            kwargs = self._process_kwargs(kwargs)
            self._logger.debug(msg, *args, **kwargs)

    def info(self, msg: Any, *args: Any, **kwargs: Any) -> None:
        if self._logger.isEnabledFor(logging.INFO):
            kwargs = self._process_kwargs(kwargs)
            self._logger.info(msg, *args, **kwargs)

    def warning(self, msg: Any, *args: Any, **kwargs: Any) -> None:
        if self._logger.isEnabledFor(logging.WARNING):
            kwargs = self._process_kwargs(kwargs)
            self._logger.warning(msg, *args, **kwargs)

    def error(self, msg: Any, *args: Any, **kwargs: Any) -> None:
        if self._logger.isEnabledFor(logging.ERROR):
            kwargs = self._process_kwargs(kwargs)
            self._logger.error(msg, *args, **kwargs)

    def critical(self, msg: Any, *args: Any, **kwargs: Any) -> None:
        if self._logger.isEnabledFor(logging.CRITICAL):
            kwargs = self._process_kwargs(kwargs)
            self._logger.critical(msg, *args, **kwargs)

    def exception(self, msg: Any, *args: Any, **kwargs: Any) -> None:
        kwargs["exc_info"] = True
        self.error(msg, *args, **kwargs)

    def log(self, level: int, msg: Any, *args: Any, **kwargs: Any) -> None:
        if self._logger.isEnabledFor(level):
            kwargs = self._process_kwargs(kwargs)
            self._logger.log(level, msg, *args, **kwargs)

    def isEnabledFor(self, level: int) -> bool:
        return self._logger.isEnabledFor(level)

    def setLevel(self, level: int) -> None:
        self._logger.setLevel(level)

    def getEffectiveLevel(self) -> int:
        return self._logger.getEffectiveLevel()

    def addHandler(self, handler: logging.Handler) -> None:
        self._logger.addHandler(handler)

    def removeHandler(self, handler: logging.Handler) -> None:
        self._logger.removeHandler(handler)

    @property
    def name(self) -> str:
        return self._logger.name

    @property
    def level(self) -> int:
        return self._logger.level

    @property
    def parent(self) -> logging.Logger | None:
        return self._logger.parent

    @property
    def propagate(self) -> bool:
        return self._logger.propagate

    @propagate.setter
    def propagate(self, value: bool) -> None:
        self._logger.propagate = value

    @property
    def handlers(self) -> list:
        return self._logger.handlers

    def __repr__(self) -> str:
        return f"<StructuredLogger name={self._logger.name!r}>"


# NOTE: We do NOT call logging.setLoggerClass() here.
# This avoids modifying global logging behavior that could affect
# third-party loggers when webscout is embedded in other Python processes.
# Instead, get_logger() returns a StructuredLogger wrapper instance.


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


def get_logger(name: str | None = None) -> StructuredLogger:
    """Return a structured logger under the ``webscout`` namespace.

    Returns a StructuredLogger wrapper that supports arbitrary keyword arguments
    for structured logging, without modifying global logging behavior.
    """
    if not _initialised:
        setup_logging()
    if name is None or name == "__main__":
        logger = logging.getLogger(_LOGGER_NAME)
    else:
        logger = logging.getLogger(f"{_LOGGER_NAME}.{name}")
    return StructuredLogger(logger)
