"""Web page monitor and alerting module for webscout-mcp.
Provides web page change monitoring and multi-channel alerting capabilities.

Features:
- Scheduled web page monitoring
- Content change detection (text, HTML, specific elements)
- Keyword monitoring (appearance, disappearance, count change)
- Price monitoring (extract and track price changes)
- Multi-channel alerts (email, webhook, DingTalk, WeCom)
- Change history tracking and comparison
- Configurable check intervals and thresholds
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from datetime import datetime

from ..logging_config import get_logger

log = get_logger(__name__)


@dataclass
class MonitorConfig:
    """Configuration for web page monitor."""

    # Check interval in seconds
    check_interval: int = 300  # 5 minutes
    # Whether to monitor text content changes
    monitor_text: bool = True
    # Whether to monitor HTML changes
    monitor_html: bool = False
    # CSS selectors to monitor (empty = whole page)
    monitor_selectors: list[str] = field(default_factory=list)
    # Keywords to monitor for appearance
    keywords_appear: list[str] = field(default_factory=list)
    # Keywords to monitor for disappearance
    keywords_disappear: list[str] = field(default_factory=list)
    # Price CSS selector (for price monitoring)
    price_selector: str = ""
    # Price change threshold (percentage, e.g., 0.05 = 5%)
    price_change_threshold: float = 0.0
    # Minimum change size to trigger alert (characters)
    min_change_size: int = 10
    # Change history storage path
    history_path: str = "~/.cache/webscout/monitor_history.json"
    # Max history entries per URL
    max_history: int = 100
    # Alert channels: email, webhook, dingtalk, wecom
    alert_channels: list[str] = field(default_factory=list)
    # Whether to include change diff in alert
    include_diff: bool = True
    # Max diff length in alert
    max_diff_length: int = 2000

    @classmethod
    def from_env(cls) -> MonitorConfig:
        """Load configuration from environment variables."""
        import os

        return cls(
            check_interval=int(os.environ.get("WEBSCOUT_MONITOR_INTERVAL", "300")),
            monitor_text=os.environ.get("WEBSCOUT_MONITOR_TEXT", "true").lower() == "true",
            monitor_html=os.environ.get("WEBSCOUT_MONITOR_HTML", "false").lower() == "true",
            min_change_size=int(os.environ.get("WEBSCOUT_MONITOR_MIN_CHANGE", "10")),
            history_path=os.environ.get("WEBSCOUT_MONITOR_HISTORY", "~/.cache/webscout/monitor_history.json"),
            max_history=int(os.environ.get("WEBSCOUT_MONITOR_MAX_HISTORY", "100")),
            include_diff=os.environ.get("WEBSCOUT_MONITOR_INCLUDE_DIFF", "true").lower() == "true",
            max_diff_length=int(os.environ.get("WEBSCOUT_MONITOR_MAX_DIFF", "2000")),
        )


@dataclass
class ChangeRecord:
    """Record of a detected change."""

    url: str
    timestamp: str
    change_type: str  # text, html, keyword_appear, keyword_disappear, price
    old_value: str = ""
    new_value: str = ""
    diff: str = ""
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "url": self.url,
            "timestamp": self.timestamp,
            "change_type": self.change_type,
            "old_value": self.old_value,
            "new_value": self.new_value,
            "diff": self.diff,
            "metadata": self.metadata,
        }


@dataclass
class AlertMessage:
    """Alert message to be sent."""

    title: str
    content: str
    url: str = ""
    change_type: str = ""
    timestamp: str = ""
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "content": self.content,
            "url": self.url,
            "change_type": self.change_type,
            "timestamp": self.timestamp,
            "metadata": self.metadata,
        }


class AlertChannel:
    """Base class for alert channels."""

    def send(self, message: AlertMessage) -> bool:
        """Send an alert message.

        Args:
            message: Alert message to send.

        Returns:
            True if sent successfully, False otherwise.
        """
        raise NotImplementedError


class WebhookAlert(AlertChannel):
    """Webhook alert channel."""

    def __init__(self, webhook_url: str, headers: dict | None = None) -> None:
        self.webhook_url = webhook_url
        self.headers = headers or {"Content-Type": "application/json"}

    def send(self, message: AlertMessage) -> bool:
        try:
            import httpx

            payload = message.to_dict()
            response = httpx.post(
                self.webhook_url,
                json=payload,
                headers=self.headers,
                timeout=10.0,
            )
            response.raise_for_status()
            log.info("Webhook alert sent", extra={"url": self.webhook_url, "title": message.title})
            return True
        except Exception as exc:
            log.error("Webhook alert failed", extra={"error": str(exc), "url": self.webhook_url})
            return False


class EmailAlert(AlertChannel):
    """Email alert channel using SMTP."""

    def __init__(
        self,
        smtp_server: str,
        smtp_port: int,
        username: str,
        password: str,
        from_addr: str,
        to_addrs: list[str],
        use_tls: bool = True,
    ) -> None:
        self.smtp_server = smtp_server
        self.smtp_port = smtp_port
        self.username = username
        self.password = password
        self.from_addr = from_addr
        self.to_addrs = to_addrs
        self.use_tls = use_tls

    def send(self, message: AlertMessage) -> bool:
        try:
            import smtplib
            from email.mime.multipart import MIMEMultipart
            from email.mime.text import MIMEText

            msg = MIMEMultipart()
            msg["From"] = self.from_addr
            msg["To"] = ", ".join(self.to_addrs)
            msg["Subject"] = message.title

            body = f"{message.content}\n\nURL: {message.url}\n时间: {message.timestamp}"
            msg.attach(MIMEText(body, "plain", "utf-8"))

            with smtplib.SMTP(self.smtp_server, self.smtp_port) as server:
                if self.use_tls:
                    server.starttls()
                server.login(self.username, self.password)
                server.sendmail(self.from_addr, self.to_addrs, msg.as_string())

            log.info("Email alert sent", extra={"to": self.to_addrs, "title": message.title})
            return True
        except Exception as exc:
            log.error("Email alert failed", extra={"error": str(exc)})
            return False


class DingTalkAlert(AlertChannel):
    """DingTalk (钉钉) robot alert channel."""

    def __init__(self, webhook_url: str, secret: str = "") -> None:
        self.webhook_url = webhook_url
        self.secret = secret

    def _sign(self) -> tuple[str, str]:
        """Generate signature for DingTalk robot."""
        import base64
        import hashlib
        import hmac
        import urllib.parse

        timestamp = str(round(time.time() * 1000))
        string_to_sign = f"{timestamp}\n{self.secret}"
        hmac_code = hmac.new(
            self.secret.encode("utf-8"),
            string_to_sign.encode("utf-8"),
            digestmod=hashlib.sha256,
        ).digest()
        sign = urllib.parse.quote_plus(base64.b64encode(hmac_code))
        return timestamp, sign

    def send(self, message: AlertMessage) -> bool:
        try:
            import httpx

            url = self.webhook_url
            if self.secret:
                timestamp, sign = self._sign()
                url = f"{url}&timestamp={timestamp}&sign={sign}"

            payload = {
                "msgtype": "text",
                "text": {
                    "content": f"{message.title}\n\n{message.content}\n\nURL: {message.url}",
                },
            }

            response = httpx.post(url, json=payload, timeout=10.0)
            response.raise_for_status()
            result = response.json()
            if result.get("errcode") == 0:
                log.info("DingTalk alert sent", extra={"title": message.title})
                return True
            else:
                log.error("DingTalk alert failed", extra={"result": result})
                return False
        except Exception as exc:
            log.error("DingTalk alert failed", extra={"error": str(exc)})
            return False


class WeComAlert(AlertChannel):
    """WeCom (企业微信) robot alert channel."""

    def __init__(self, webhook_url: str) -> None:
        self.webhook_url = webhook_url

    def send(self, message: AlertMessage) -> bool:
        try:
            import httpx

            payload = {
                "msgtype": "text",
                "text": {
                    "content": f"{message.title}\n\n{message.content}\n\nURL: {message.url}",
                },
            }

            response = httpx.post(self.webhook_url, json=payload, timeout=10.0)
            response.raise_for_status()
            result = response.json()
            if result.get("errcode") == 0:
                log.info("WeCom alert sent", extra={"title": message.title})
                return True
            else:
                log.error("WeCom alert failed", extra={"result": result})
                return False
        except Exception as exc:
            log.error("WeCom alert failed", extra={"error": str(exc)})
            return False


class WebMonitor:
    """Web page monitor with change detection and alerting.

    Monitors web pages for changes and sends alerts through multiple channels.
    """

    def __init__(
        self,
        config: MonitorConfig | None = None,
        fetcher=None,
    ) -> None:
        self.config = config or MonitorConfig.from_env()
        self.fetcher = fetcher
        self._history: dict[str, list[ChangeRecord]] = {}
        self._last_content: dict[str, dict] = {}
        self._alert_channels: list[AlertChannel] = []
        self._load_history()

    def add_alert_channel(self, channel: AlertChannel) -> None:
        """Add an alert channel."""
        self._alert_channels.append(channel)
        log.info("Alert channel added", extra={"type": type(channel).__name__})

    def _load_history(self) -> None:
        """Load change history from file."""
        import os

        history_path = os.path.expanduser(self.config.history_path)
        if os.path.exists(history_path):
            try:
                with open(history_path, "r") as f:
                    data = json.load(f)
                for url, records in data.items():
                    self._history[url] = [ChangeRecord(**r) for r in records]
                log.info("Monitor history loaded", extra={"path": history_path, "urls": len(self._history)})
            except Exception as exc:
                log.warning("Failed to load monitor history", extra={"error": str(exc)})

    def _save_history(self) -> None:
        """Save change history to file."""
        import os

        history_path = os.path.expanduser(self.config.history_path)
        os.makedirs(os.path.dirname(history_path), exist_ok=True)
        try:
            data = {}
            for url, records in self._history.items():
                data[url] = [r.to_dict() for r in records[-self.config.max_history :]]
            with open(history_path, "w") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as exc:
            log.warning("Failed to save monitor history", extra={"error": str(exc)})

    def _get_content(self, url: str) -> tuple[str, str]:
        """Get page content (text and HTML).

        Args:
            url: URL to fetch.

        Returns:
            Tuple of (text_content, html_content).
        """
        if self.fetcher:
            result = self.fetcher.fetch(url)
            if hasattr(result, "content") and hasattr(result, "html"):
                return result.content, result.html
            return str(result), ""

        # Fallback to simple HTTP fetch
        try:
            import httpx

            from ..fetcher import get_default_headers

            response = httpx.get(url, headers=get_default_headers(), timeout=30.0)
            response.raise_for_status()
            html = response.text
            # Simple text extraction
            try:
                from bs4 import BeautifulSoup

                soup = BeautifulSoup(html, "html.parser")
                text = soup.get_text(separator="\n", strip=True)
            except ImportError:
                text = html
            return text, html
        except Exception as exc:
            log.error("Failed to fetch URL for monitoring", extra={"url": url, "error": str(exc)})
            return "", ""

    def _compute_hash(self, content: str) -> str:
        """Compute hash of content."""
        return hashlib.md5(content.encode("utf-8")).hexdigest()

    def _generate_diff(self, old: str, new: str) -> str:
        """Generate a simple diff between old and new content."""
        import difflib

        old_lines = old.splitlines()
        new_lines = new.splitlines()
        diff = difflib.unified_diff(
            old_lines,
            new_lines,
            fromfile="old",
            tofile="new",
            lineterm="",
        )
        diff_text = "\n".join(diff)
        if len(diff_text) > self.config.max_diff_length:
            diff_text = diff_text[: self.config.max_diff_length] + "\n... (truncated)"
        return diff_text

    def check_url(self, url: str) -> list[ChangeRecord]:
        """Check a URL for changes.

        Args:
            url: URL to check.

        Returns:
            List of detected changes.
        """
        changes = []
        text, html = self._get_content(url)

        if not text and not html:
            log.warning("Empty content for monitoring", extra={"url": url})
            return changes

        timestamp = datetime.now().isoformat()

        # Check text changes
        if self.config.monitor_text and text:
            text_hash = self._compute_hash(text)
            last = self._last_content.get(url, {})
            if "text_hash" in last and last["text_hash"] != text_hash:
                old_text = last.get("text", "")
                change_size = abs(len(text) - len(old_text))
                if change_size >= self.config.min_change_size:
                    diff = self._generate_diff(old_text, text) if self.config.include_diff else ""
                    change = ChangeRecord(
                        url=url,
                        timestamp=timestamp,
                        change_type="text",
                        old_value=old_text[:500],
                        new_value=text[:500],
                        diff=diff,
                        metadata={"change_size": change_size},
                    )
                    changes.append(change)
            self._last_content.setdefault(url, {})["text_hash"] = text_hash
            self._last_content[url]["text"] = text

        # Check HTML changes
        if self.config.monitor_html and html:
            html_hash = self._compute_hash(html)
            last = self._last_content.get(url, {})
            if "html_hash" in last and last["html_hash"] != html_hash:
                change = ChangeRecord(
                    url=url,
                    timestamp=timestamp,
                    change_type="html",
                    old_value=last.get("html_hash", ""),
                    new_value=html_hash,
                    metadata={},
                )
                changes.append(change)
            self._last_content.setdefault(url, {})["html_hash"] = html_hash

        # Check keyword appearance
        for keyword in self.config.keywords_appear:
            if keyword in text and keyword not in self._last_content.get(url, {}).get("keywords", []):
                change = ChangeRecord(
                    url=url,
                    timestamp=timestamp,
                    change_type="keyword_appear",
                    old_value="",
                    new_value=keyword,
                    metadata={"keyword": keyword},
                )
                changes.append(change)

        # Check keyword disappearance
        for keyword in self.config.keywords_disappear:
            if keyword not in text and keyword in self._last_content.get(url, {}).get("keywords", []):
                change = ChangeRecord(
                    url=url,
                    timestamp=timestamp,
                    change_type="keyword_disappear",
                    old_value=keyword,
                    new_value="",
                    metadata={"keyword": keyword},
                )
                changes.append(change)

        # Update keyword tracking
        current_keywords = [kw for kw in self.config.keywords_appear + self.config.keywords_disappear if kw in text]
        self._last_content.setdefault(url, {})["keywords"] = current_keywords

        # Record changes in history
        if changes:
            self._history.setdefault(url, []).extend(changes)
            self._save_history()
            self._send_alerts(changes)

        return changes

    def _send_alerts(self, changes: list[ChangeRecord]) -> None:
        """Send alerts for detected changes."""
        if not self._alert_channels:
            return

        for change in changes:
            title = f"[网页监控] {change.change_type} - {change.url}"
            content_parts = [f"变化类型: {change.change_type}"]
            if change.old_value:
                content_parts.append(f"旧值: {change.old_value[:200]}")
            if change.new_value:
                content_parts.append(f"新值: {change.new_value[:200]}")
            if change.diff:
                content_parts.append(f"差异:\n{change.diff}")

            message = AlertMessage(
                title=title,
                content="\n".join(content_parts),
                url=change.url,
                change_type=change.change_type,
                timestamp=change.timestamp,
                metadata=change.metadata,
            )

            for channel in self._alert_channels:
                try:
                    channel.send(message)
                except Exception as exc:
                    log.error("Failed to send alert", extra={"channel": type(channel).__name__, "error": str(exc)})

    def get_history(self, url: str, limit: int = 50) -> list[ChangeRecord]:
        """Get change history for a URL.

        Args:
            url: URL to get history for.
            limit: Maximum number of records to return.

        Returns:
            List of change records.
        """
        records = self._history.get(url, [])
        return records[-limit:]

    def get_all_history(self) -> dict[str, list[ChangeRecord]]:
        """Get all change history."""
        return self._history

    def clear_history(self, url: str | None = None) -> None:
        """Clear change history.

        Args:
            url: URL to clear history for. If None, clear all history.
        """
        if url:
            self._history.pop(url, None)
        else:
            self._history.clear()
        self._save_history()
        log.info("Monitor history cleared", extra={"url": url or "all"})

    def get_stats(self) -> dict:
        """Get monitor statistics."""
        total_changes = sum(len(records) for records in self._history.values())
        return {
            "monitored_urls": len(self._history),
            "total_changes": total_changes,
            "alert_channels": len(self._alert_channels),
            "check_interval": self.config.check_interval,
            "history_path": self.config.history_path,
        }


def is_monitor_available() -> bool:
    """Check if web monitor is available."""
    return True  # Monitor module has no hard dependencies
