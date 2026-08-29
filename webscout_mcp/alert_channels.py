"""Compatibility shim for alert_channels module.

This module has been moved to webscout_mcp.extras.alert_channels.
This file provides backward compatibility for existing imports.

Deprecated:
    Import from webscout_mcp.extras.alert_channels instead.
    This compatibility shim will be removed in a future version.
"""

from __future__ import annotations

import warnings

from .extras.alert_channels import *  # noqa: F401,F403
from .extras.alert_channels import (
    AlertMessage,
    AlertResult,
    BaseAlertChannel,
    WebhookAlert,
    EmailAlert,
    DingTalkAlert,
    WeComAlert,
    FeishuAlert,
    SlackAlert,
    TelegramAlert,
    ServerChanAlert,
    AlertManager,
    create_alert_manager,
)

warnings.warn(
    "webscout_mcp.alert_channels is deprecated, "
    "import from webscout_mcp.extras.alert_channels instead.",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = [
    "AlertMessage",
    "AlertResult",
    "BaseAlertChannel",
    "WebhookAlert",
    "EmailAlert",
    "DingTalkAlert",
    "WeComAlert",
    "FeishuAlert",
    "SlackAlert",
    "TelegramAlert",
    "ServerChanAlert",
    "AlertManager",
    "create_alert_manager",
]
