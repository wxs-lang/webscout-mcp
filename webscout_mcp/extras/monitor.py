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
    # Noise suppression, applied before hashing so a filtered difference cannot
    # produce a false positive. ignore_text strips values that change every request
    # (timestamps, session ids); ignore_selector removes whole churning regions.
    ignore_text: list[str] = field(default_factory=list)
    ignore_selector: list[str] = field(default_factory=list)

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


# Reserved key inside the history file for the comparison baseline. Leading
# underscores keep it from colliding with any URL.
_BASELINE_KEY = "__baseline__"


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


def _to_channel_message(change: ChangeRecord, source: AlertMessage):
    """Convert this module's AlertMessage into the channel-side one.

    Two dataclasses share the name `AlertMessage` but not their fields: the monitor's has
    ``change_type`` and an ISO-format timestamp; :mod:`alert_channels`' has ``level`` and a
    float timestamp, and its ``format_message`` reads ``level``. Handing the monitor's
    object straight to a channel therefore fails at send time, which the per-channel
    try/except hides.

    Converting here keeps each module's own shape intact and puts the adapter in one
    place instead of asking either module to know about the other.
    """
    from .alert_channels import AlertMessage as ChannelMessage

    return ChannelMessage(
        title=source.title,
        content=source.content,
        level="info",
        url=source.url,
        metadata={
            **dict(source.metadata or {}),
            "change_type": change.change_type,
            "change_timestamp": change.timestamp,
        },
        timestamp=_epoch_from_isoformat(change.timestamp),
    )


def _epoch_from_isoformat(value) -> float:
    """Epoch seconds from an isoformat string, falling back to now.

    ``ChangeRecord.timestamp`` is an ISO string; the channel-side message wants a float.
    """
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return datetime.fromisoformat(str(value)).timestamp()
    except (TypeError, ValueError):
        return datetime.now().timestamp()


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
                with open(history_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                # The baseline lives under a reserved key so files written before it
                # existed still parse - they simply yield no baseline, which falls back to
                # "first check establishes one" rather than raising.
                baseline = data.pop(_BASELINE_KEY, None)
                if isinstance(baseline, dict):
                    self._last_content = baseline
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
            # `_last_content` holds the hashes and prices the next check compares against.
            # Without it every restart re-establishes a baseline and can never report a
            # change, which is the whole point of the tool.
            if self._last_content:
                data[_BASELINE_KEY] = self._last_content
            with open(history_path, "w", encoding="utf-8") as f:
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

    def _changed_char_count(self, old: str, new: str) -> int:
        """Characters that differ between two texts.

        Sums non-matching diff blocks: removed characters plus inserted ones. Replacing a
        word counts twice, which is the right magnitude for a threshold that should ignore
        trivia while catching edits.
        """
        if old == new:
            return 0
        import difflib

        matcher = difflib.SequenceMatcher(None, old, new, autojunk=False)
        total = 0
        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag == "equal":
                continue
            total += (i2 - i1) + (j2 - j1)
        return total

    def _apply_ignore_filters(self, text: str, html: str) -> tuple[str, str]:
        """Strip configured noise before comparison.

        Two mechanisms, both needed: ``ignore_text`` removes values that change on every
        request (timestamps, session ids, cache busters); ``ignore_selector`` removes
        whole regions (ad slots, "you may also like") whose content churns independently
        of the page being watched.

        Selector removal re-extracts text from the cleaned HTML so a removed region cannot
        keep influencing the text comparison. A bad selector is logged and skipped rather
        than aborting the check.
        """
        ignore_text = getattr(self.config, "ignore_text", None) or []
        ignore_selector = getattr(self.config, "ignore_selector", None) or []

        if ignore_text:
            import re as _re

            for pattern in ignore_text:
                if not pattern:
                    continue
                try:
                    text = _re.sub(pattern, "", text)
                except _re.error:
                    text = text.replace(pattern, "")

        if ignore_selector and html:
            try:
                from bs4 import BeautifulSoup

                soup = BeautifulSoup(html, "html.parser")
                removed = False
                for selector in ignore_selector:
                    if not selector:
                        continue
                    try:
                        for node in soup.select(selector):
                            node.decompose()
                            removed = True
                    except Exception:  # noqa: BLE001 - one bad selector must not stop the check
                        log.warning("monitor: invalid ignore_selector", extra={"selector": selector})
                if removed:
                    html = str(soup)
                    text = soup.get_text(separator="\n", strip=True)
            except ImportError:
                log.warning("monitor: ignore_selector needs beautifulsoup4; filters skipped")

        return text, html

    def _extract_price(self, html: str) -> float | None:
        """Numeric price from the configured selector, or None.

        ``price_selector`` and ``price_change_threshold`` were declared in MonitorConfig
        and never implemented, so the documented price monitoring did nothing. Extraction
        lives here so ``check_url`` stays readable and this is testable on its own.
        """
        selector = getattr(self.config, "price_selector", "") or ""
        if not selector or not html:
            return None
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            log.warning("monitor: price_selector needs beautifulsoup4; skipped")
            return None
        try:
            soup = BeautifulSoup(html, "html.parser")
            node = soup.select_one(selector)
            if node is None:
                return None
            raw = node.get_text(separator=" ", strip=True)
        except Exception:  # noqa: BLE001 - a bad selector must not abort the check
            log.warning("monitor: invalid price_selector", extra={"selector": selector})
            return None

        import re as _re

        match = _re.search(r"-?\d[\d,\s]*(?:\.\d+)?", raw)
        if not match:
            return None
        cleaned = match.group(0).replace(",", "").replace(" ", "")
        try:
            return float(cleaned)
        except ValueError:
            return None

    def _compute_hash(self, content: str) -> str:
        """Compute hash of content."""
        return hashlib.md5(content.encode("utf-8"), usedforsecurity=False).hexdigest()

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
        text, html = self._apply_ignore_filters(text, html)

        if not text and not html:
            log.warning("Empty content for monitoring", extra={"url": url})
            return changes

        timestamp = datetime.now().isoformat()
        # Snapshot of what we are comparing against, so the save condition below can tell
        # whether this run established or moved the baseline.
        self._baseline_before_check = dict(self._last_content.get(url, {}))

        # Check text changes
        if self.config.monitor_text and text:
            text_hash = self._compute_hash(text)
            last = self._last_content.get(url, {})
            if "text_hash" in last and last["text_hash"] != text_hash:
                old_text = last.get("text", "")
                # Measure what changed, not how the lengths differ. abs(len diff)
                # reports 0 for "$100.00" -> "$900.00" and for any same-length
                # rewrite, so the changes a monitor exists to catch were invisible.
                change_size = self._changed_char_count(old_text, text)
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

        # Price change. Independent of min_change_size on purpose: "$100.00" ->
        # "$900.00" differs by one character, so a text-change threshold swallows it, yet
        # it is the most important change on a product page. Compared as a percentage.
        price_selector = getattr(self.config, "price_selector", "") or ""
        if price_selector and html:
            new_price = self._extract_price(html)
            last = self._last_content.setdefault(url, {})
            old_price = last.get("price")
            if new_price is not None and old_price is not None:
                delta = new_price - old_price
                pct = abs(delta) / old_price if old_price else 0.0
                threshold = getattr(self.config, "price_change_threshold", 0.0) or 0.0
                if delta != 0 and pct >= threshold:
                    changes.append(
                        ChangeRecord(
                            url=url,
                            timestamp=timestamp,
                            change_type="price",
                            old_value=f"{old_price:g}",
                            new_value=f"{new_price:g}",
                            diff=f"{old_price:g} -> {new_price:g} ({pct * 100:.2f}%)",
                            metadata={
                                "old_price": old_price,
                                "new_price": new_price,
                                "change_pct": round(pct, 6),
                                "threshold": threshold,
                            },
                        )
                    )
            if new_price is not None:
                last["price"] = new_price

        # Persist whenever the baseline moved, not only when something was reported.
        #
        # `_last_content` is what the next comparison is made against. Saving it only on
        # a detected change means the first check for a URL - which by definition reports
        # nothing - leaves no baseline on disk, so the next process starts empty and can
        # never report a change at all. The tool exposed exactly that: three calls, three
        # fresh baselines, no changes ever.
        if changes or self._last_content.get(url) != self._baseline_before_check:
            self._history.setdefault(url, []).extend(changes)
            self._save_history()
        self.last_delivery = self._send_alerts(changes) if changes else []

        return changes

    def _send_alerts(self, changes: list[ChangeRecord]) -> list[dict]:
        """Send alerts for detected changes.

        Returns one entry per attempted send. The result used to be discarded, so a
        channel that failed - wrong URL, missing dependency, non-2xx - was indistinguishable
        from one that delivered, and the caller had no way to notice.
        """
        if not self._alert_channels:
            return []

        outcomes: list[dict] = []

        for change in changes:
            title = f"[网页监控] {change.change_type} - {change.url}"
            content_parts = [f"变化类型: {change.change_type}"]
            if change.old_value:
                content_parts.append(f"旧值: {change.old_value[:200]}")
            if change.new_value:
                content_parts.append(f"新值: {change.new_value[:200]}")
            if change.diff:
                content_parts.append(f"差异:\n{change.diff}")

            # `monitor.AlertMessage` and `alert_channels.AlertMessage` are two different
            # dataclasses with different fields: this module's carries `change_type` and
            # an ISO timestamp, the channel-side one carries `level` and a float timestamp.
            # Channels call `message.level`, so passing this module's class raised
            # AttributeError for every change - swallowed by the per-channel try/except and
            # logged, which is why notifications looked wired up but never fired.
            message = AlertMessage(
                title=title,
                content="\n".join(content_parts),
                url=change.url,
                change_type=change.change_type,
                timestamp=change.timestamp,
                metadata=change.metadata,
            )

            channel_message = _to_channel_message(change, message)
            for channel in self._alert_channels:
                try:
                    result = channel.send(channel_message)
                    outcomes.append(
                        {
                            "channel": getattr(result, "channel", type(channel).__name__),
                            "success": bool(getattr(result, "success", False)),
                            "message": getattr(result, "message", "") or "",
                            "error": getattr(result, "error", None),
                        }
                    )
                except Exception as exc:
                    log.error(
                        "Failed to send alert",
                        extra={"channel": type(channel).__name__, "error": str(exc)},
                    )
                    outcomes.append(
                        {
                            "channel": type(channel).__name__,
                            "success": False,
                            "message": "",
                            "error": str(exc),
                        }
                    )

        return outcomes

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
