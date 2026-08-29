"""Compatibility shim for monitor module.

This module has been moved to webscout_mcp.extras.monitor.
This file provides backward compatibility for existing imports.

Deprecated:
    Import from webscout_mcp.extras.monitor instead.
    This compatibility shim will be removed in a future version.
"""

from __future__ import annotations

import warnings

from .extras.monitor import *  # noqa: F401,F403
from .extras.monitor import (
    MonitorConfig,
    ChangeRecord,
    AlertMessage,
    AlertChannel,
    WebhookAlert,
    EmailAlert,
    DingTalkAlert,
    WeComAlert,
    WebMonitor,
    is_monitor_available,
)

warnings.warn(
    "webscout_mcp.monitor is deprecated, "
    "import from webscout_mcp.extras.monitor instead.",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = [
    "MonitorConfig",
    "ChangeRecord",
    "AlertMessage",
    "AlertChannel",
    "WebhookAlert",
    "EmailAlert",
    "DingTalkAlert",
    "WeComAlert",
    "WebMonitor",
    "is_monitor_available",
]
