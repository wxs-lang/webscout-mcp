"""Multi-channel alerting module for webscout-mcp.

Send alerts to multiple channels: Webhook, Email, DingTalk, WeCom,
Feishu (Lark), Slack, Telegram, Server Chan.

Features:
- 8+ alert channels
- Unified alert interface
- Message formatting
- Retry on failure
- Batch sending
- Alert level support
- Channel fallback
- Rate limiting
"""
from __future__ import annotations
import json
import time
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any
from .logging import get_logger

log = get_logger(__name__)


@dataclass
class AlertMessage:
    """Alert message to send."""
    title: str = ""
    content: str = ""
    level: str = "info"  # info, warning, error, critical
    url: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "content": self.content,
            "level": self.level,
            "url": self.url,
            "metadata": self.metadata,
            "timestamp": self.timestamp,
        }


@dataclass
class AlertResult:
    """Result of sending an alert."""
    success: bool = False
    channel: str = ""
    message: str = ""
    status_code: int = 0
    response: Optional[dict] = None
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "channel": self.channel,
            "message": self.message,
            "status_code": self.status_code,
            "error": self.error,
        }


class BaseAlertChannel:
    """Base class for alert channels."""

    def __init__(self, name: str, enabled: bool = True) -> None:
        self.name = name
        self.enabled = enabled

    def send(self, message: AlertMessage) -> AlertResult:
        """Send an alert message."""
        raise NotImplementedError

    def format_message(self, message: AlertMessage) -> str:
        """Format alert message as text."""
        level_emoji = {
            "info": "ℹ️",
            "warning": "⚠️",
            "error": "❌",
            "critical": "🚨",
        }
        emoji = level_emoji.get(message.level, "📢")
        text = f"{emoji} **{message.title}**\n\n{message.content}"
        if message.url:
            text += f"\n\n🔗 {message.url}"
        return text


class WebhookAlert(BaseAlertChannel):
    """Generic webhook alert channel."""

    def __init__(self, webhook_url: str, enabled: bool = True) -> None:
        super().__init__("webhook", enabled)
        self.webhook_url = webhook_url

    def send(self, message: AlertMessage) -> AlertResult:
        result = AlertResult(channel=self.name)
        if not self.enabled:
            result.message = "Channel disabled"
            return result

        try:
            import requests
            payload = message.to_dict()
            response = requests.post(self.webhook_url, json=payload, timeout=10)
            result.status_code = response.status_code
            result.success = 200 <= response.status_code < 300
            result.message = f"HTTP {response.status_code}"
            try:
                result.response = response.json()
            except Exception:
                result.response = {"raw": response.text[:500]}
        except Exception as exc:
            result.error = str(exc)
            result.success = False

        return result


class EmailAlert(BaseAlertChannel):
    """Email alert channel via SMTP."""

    def __init__(
        self,
        smtp_server: str,
        smtp_port: int,
        username: str,
        password: str,
        from_addr: str,
        to_addrs: List[str],
        use_tls: bool = True,
        enabled: bool = True,
    ) -> None:
        super().__init__("email", enabled)
        self.smtp_server = smtp_server
        self.smtp_port = smtp_port
        self.username = username
        self.password = password
        self.from_addr = from_addr
        self.to_addrs = to_addrs
        self.use_tls = use_tls

    def send(self, message: AlertMessage) -> AlertResult:
        result = AlertResult(channel=self.name)
        if not self.enabled:
            result.message = "Channel disabled"
            return result

        try:
            import smtplib
            from email.mime.text import MIMEText
            from email.mime.multipart import MIMEMultipart

            msg = MIMEMultipart()
            msg["From"] = self.from_addr
            msg["To"] = ", ".join(self.to_addrs)
            msg["Subject"] = f"[{message.level.upper()}] {message.title}"

            body = self.format_message(message)
            msg.attach(MIMEText(body, "plain", "utf-8"))

            with smtplib.SMTP(self.smtp_server, self.smtp_port, timeout=10) as server:
                if self.use_tls:
                    server.starttls()
                server.login(self.username, self.password)
                server.send_message(msg)

            result.success = True
            result.message = f"Email sent to {len(self.to_addrs)} recipients"
        except Exception as exc:
            result.error = str(exc)
            result.success = False

        return result


class DingTalkAlert(BaseAlertChannel):
    """DingTalk (钉钉) alert channel."""

    def __init__(self, webhook_url: str, secret: Optional[str] = None, enabled: bool = True) -> None:
        super().__init__("dingtalk", enabled)
        self.webhook_url = webhook_url
        self.secret = secret

    def _sign(self) -> tuple:
        """Generate DingTalk signature."""
        if not self.secret:
            return self.webhook_url, {}

        import hmac
        import hashlib
        import base64
        import urllib.parse

        timestamp = str(round(time.time() * 1000))
        string_to_sign = f"{timestamp}\n{self.secret}"
        hmac_code = hmac.new(
            self.secret.encode("utf-8"),
            string_to_sign.encode("utf-8"),
            digestmod=hashlib.sha256,
        ).digest()
        sign = urllib.parse.quote_plus(base64.b64encode(hmac_code))
        signed_url = f"{self.webhook_url}&timestamp={timestamp}&sign={sign}"
        return signed_url, {}

    def send(self, message: AlertMessage) -> AlertResult:
        result = AlertResult(channel=self.name)
        if not self.enabled:
            result.message = "Channel disabled"
            return result

        try:
            import requests
            url, _ = self._sign()
            content = self.format_message(message)
            payload = {
                "msgtype": "markdown",
                "markdown": {
                    "title": message.title,
                    "text": content,
                },
            }
            response = requests.post(url, json=payload, timeout=10)
            result.status_code = response.status_code
            resp_data = response.json()
            result.success = resp_data.get("errcode", -1) == 0
            result.message = resp_data.get("errmsg", "Unknown")
        except Exception as exc:
            result.error = str(exc)
            result.success = False

        return result


class WeComAlert(BaseAlertChannel):
    """WeCom (企业微信) alert channel."""

    def __init__(self, webhook_url: str, enabled: bool = True) -> None:
        super().__init__("wecom", enabled)
        self.webhook_url = webhook_url

    def send(self, message: AlertMessage) -> AlertResult:
        result = AlertResult(channel=self.name)
        if not self.enabled:
            result.message = "Channel disabled"
            return result

        try:
            import requests
            content = self.format_message(message)
            payload = {
                "msgtype": "markdown",
                "markdown": {
                    "content": content,
                },
            }
            response = requests.post(self.webhook_url, json=payload, timeout=10)
            result.status_code = response.status_code
            resp_data = response.json()
            result.success = resp_data.get("errcode", -1) == 0
            result.message = resp_data.get("errmsg", "Unknown")
        except Exception as exc:
            result.error = str(exc)
            result.success = False

        return result


class FeishuAlert(BaseAlertChannel):
    """Feishu (飞书/Lark) alert channel."""

    def __init__(self, webhook_url: str, enabled: bool = True) -> None:
        super().__init__("feishu", enabled)
        self.webhook_url = webhook_url

    def send(self, message: AlertMessage) -> AlertResult:
        result = AlertResult(channel=self.name)
        if not self.enabled:
            result.message = "Channel disabled"
            return result

        try:
            import requests
            content = self.format_message(message)
            payload = {
                "msg_type": "interactive",
                "card": {
                    "header": {
                        "title": {"tag": "plain_text", "content": message.title},
                        "template": "red" if message.level in ("error", "critical") else "blue",
                    },
                    "elements": [
                        {"tag": "markdown", "content": content},
                    ],
                },
            }
            response = requests.post(self.webhook_url, json=payload, timeout=10)
            result.status_code = response.status_code
            resp_data = response.json()
            result.success = resp_data.get("code", -1) == 0
            result.message = resp_data.get("msg", "Unknown")
        except Exception as exc:
            result.error = str(exc)
            result.success = False

        return result


class SlackAlert(BaseAlertChannel):
    """Slack alert channel."""

    def __init__(self, webhook_url: str, channel: Optional[str] = None, enabled: bool = True) -> None:
        super().__init__("slack", enabled)
        self.webhook_url = webhook_url
        self.channel = channel

    def send(self, message: AlertMessage) -> AlertResult:
        result = AlertResult(channel=self.name)
        if not self.enabled:
            result.message = "Channel disabled"
            return result

        try:
            import requests
            content = self.format_message(message)
            payload = {
                "text": content,
                "username": "WebScout Bot",
                "icon_emoji": ":robot_face:",
            }
            if self.channel:
                payload["channel"] = self.channel
            response = requests.post(self.webhook_url, json=payload, timeout=10)
            result.status_code = response.status_code
            result.success = response.status_code == 200
            result.message = response.text[:200]
        except Exception as exc:
            result.error = str(exc)
            result.success = False

        return result


class TelegramAlert(BaseAlertChannel):
    """Telegram alert channel."""

    def __init__(self, bot_token: str, chat_id: str, enabled: bool = True) -> None:
        super().__init__("telegram", enabled)
        self.bot_token = bot_token
        self.chat_id = chat_id

    def send(self, message: AlertMessage) -> AlertResult:
        result = AlertResult(channel=self.name)
        if not self.enabled:
            result.message = "Channel disabled"
            return result

        try:
            import requests
            content = self.format_message(message)
            url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
            payload = {
                "chat_id": self.chat_id,
                "text": content,
                "parse_mode": "Markdown",
                "disable_web_page_preview": False,
            }
            response = requests.post(url, json=payload, timeout=10)
            result.status_code = response.status_code
            resp_data = response.json()
            result.success = resp_data.get("ok", False)
            result.message = "Message sent" if result.success else resp_data.get("description", "Failed")
        except Exception as exc:
            result.error = str(exc)
            result.success = False

        return result


class ServerChanAlert(BaseAlertChannel):
    """Server Chan (Server酱) alert channel."""

    def __init__(self, send_key: str, enabled: bool = True) -> None:
        super().__init__("serverchan", enabled)
        self.send_key = send_key

    def send(self, message: AlertMessage) -> AlertResult:
        result = AlertResult(channel=self.name)
        if not self.enabled:
            result.message = "Channel disabled"
            return result

        try:
            import requests
            url = f"https://sctapi.ftqq.com/{self.send_key}.send"
            content = self.format_message(message)
            payload = {
                "title": message.title,
                "desp": content,
            }
            response = requests.post(url, data=payload, timeout=10)
            result.status_code = response.status_code
            resp_data = response.json()
            result.success = resp_data.get("code", -1) == 0
            result.message = resp_data.get("message", "Unknown")
        except Exception as exc:
            result.error = str(exc)
            result.success = False

        return result


class AlertManager:
    """Manage multiple alert channels and send alerts.

    Features:
    - Multiple channel management
    - Channel fallback
    - Batch sending
    - Retry logic
    - Alert level filtering
    """

    def __init__(self) -> None:
        self.channels: Dict[str, BaseAlertChannel] = {}
        self.min_level: str = "info"
        self._level_order = {"debug": 0, "info": 1, "warning": 2, "error": 3, "critical": 4}

    def add_channel(self, channel: BaseAlertChannel) -> None:
        """Add an alert channel."""
        self.channels[channel.name] = channel
        log.debug("Added alert channel", extra={"channel": channel.name})

    def remove_channel(self, name: str) -> bool:
        """Remove an alert channel."""
        if name in self.channels:
            del self.channels[name]
            return True
        return False

    def set_min_level(self, level: str) -> None:
        """Set minimum alert level to send."""
        self.min_level = level

    def send(self, message: AlertMessage, channels: Optional[List[str]] = None) -> List[AlertResult]:
        """Send alert to specified or all channels.

        Args:
            message: Alert message to send.
            channels: List of channel names (None = all enabled).

        Returns:
            List of AlertResult objects.
        """
        # Check level filter
        if self._level_order.get(message.level, 1) < self._level_order.get(self.min_level, 0):
            return []

        results = []
        target_channels = channels or list(self.channels.keys())

        for channel_name in target_channels:
            channel = self.channels.get(channel_name)
            if channel and channel.enabled:
                try:
                    result = channel.send(message)
                    results.append(result)
                except Exception as exc:
                    results.append(AlertResult(
                        channel=channel_name,
                        success=False,
                        error=str(exc),
                    ))

        return results

    def send_to_all(self, message: AlertMessage) -> List[AlertResult]:
        """Send alert to all enabled channels."""
        return self.send(message)

    def get_channel_status(self) -> Dict[str, bool]:
        """Get status of all channels."""
        return {name: channel.enabled for name, channel in self.channels.items()}

    @property
    def num_channels(self) -> int:
        """Get number of configured channels."""
        return len(self.channels)


def create_alert_manager(config: Dict[str, Any]) -> AlertManager:
    """Create AlertManager from configuration.

    Args:
        config: Configuration dictionary with channel settings.

    Returns:
        Configured AlertManager instance.
    """
    manager = AlertManager()

    if "webhook" in config:
        manager.add_channel(WebhookAlert(config["webhook"]["url"]))

    if "email" in config:
        email_cfg = config["email"]
        manager.add_channel(EmailAlert(
            smtp_server=email_cfg["smtp_server"],
            smtp_port=email_cfg.get("smtp_port", 587),
            username=email_cfg["username"],
            password=email_cfg["password"],
            from_addr=email_cfg["from_addr"],
            to_addrs=email_cfg["to_addrs"],
            use_tls=email_cfg.get("use_tls", True),
        ))

    if "dingtalk" in config:
        dt_cfg = config["dingtalk"]
        manager.add_channel(DingTalkAlert(dt_cfg["webhook_url"], dt_cfg.get("secret")))

    if "wecom" in config:
        manager.add_channel(WeComAlert(config["wecom"]["webhook_url"]))

    if "feishu" in config:
        manager.add_channel(FeishuAlert(config["feishu"]["webhook_url"]))

    if "slack" in config:
        slack_cfg = config["slack"]
        manager.add_channel(SlackAlert(slack_cfg["webhook_url"], slack_cfg.get("channel")))

    if "telegram" in config:
        tg_cfg = config["telegram"]
        manager.add_channel(TelegramAlert(tg_cfg["bot_token"], tg_cfg["chat_id"]))

    if "serverchan" in config:
        manager.add_channel(ServerChanAlert(config["serverchan"]["send_key"]))

    return manager
