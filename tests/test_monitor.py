"""Tests for web monitor module."""

import pytest

from webscout_mcp.monitor import (
    AlertChannel,
    AlertMessage,
    ChangeRecord,
    DingTalkAlert,
    EmailAlert,
    MonitorConfig,
    WebhookAlert,
    WebMonitor,
    WeComAlert,
    is_monitor_available,
)


class TestMonitorConfig:
    """Test monitor configuration."""

    def test_default_config(self):
        config = MonitorConfig()
        assert config.check_interval == 300
        assert config.monitor_text is True
        assert config.monitor_html is False
        assert config.min_change_size == 10
        assert config.max_history == 100
        assert config.include_diff is True
        assert config.max_diff_length == 2000

    def test_custom_config(self):
        config = MonitorConfig(
            check_interval=60,
            monitor_text=False,
            monitor_html=True,
            min_change_size=100,
            max_history=50,
            include_diff=False,
        )
        assert config.check_interval == 60
        assert config.monitor_text is False
        assert config.monitor_html is True
        assert config.min_change_size == 100
        assert config.max_history == 50
        assert config.include_diff is False

    def test_from_env(self, monkeypatch):
        monkeypatch.setenv("WEBSCOUT_MONITOR_INTERVAL", "120")
        monkeypatch.setenv("WEBSCOUT_MONITOR_TEXT", "false")
        monkeypatch.setenv("WEBSCOUT_MONITOR_HTML", "true")
        monkeypatch.setenv("WEBSCOUT_MONITOR_MIN_CHANGE", "50")
        monkeypatch.setenv("WEBSCOUT_MONITOR_MAX_HISTORY", "200")
        monkeypatch.setenv("WEBSCOUT_MONITOR_INCLUDE_DIFF", "false")

        config = MonitorConfig.from_env()
        assert config.check_interval == 120
        assert config.monitor_text is False
        assert config.monitor_html is True
        assert config.min_change_size == 50
        assert config.max_history == 200
        assert config.include_diff is False


class TestChangeRecord:
    """Test ChangeRecord class."""

    def test_change_record_creation(self):
        record = ChangeRecord(
            url="https://example.com",
            timestamp="2024-01-01T00:00:00",
            change_type="text",
            old_value="old content",
            new_value="new content",
        )
        assert record.url == "https://example.com"
        assert record.change_type == "text"
        assert record.old_value == "old content"
        assert record.new_value == "new content"

    def test_change_record_to_dict(self):
        record = ChangeRecord(
            url="https://example.com",
            timestamp="2024-01-01T00:00:00",
            change_type="text",
            metadata={"key": "value"},
        )
        data = record.to_dict()
        assert data["url"] == "https://example.com"
        assert data["change_type"] == "text"
        assert data["metadata"] == {"key": "value"}


class TestAlertMessage:
    """Test AlertMessage class."""

    def test_alert_message_creation(self):
        message = AlertMessage(
            title="Test Alert",
            content="Alert content",
            url="https://example.com",
            change_type="text",
        )
        assert message.title == "Test Alert"
        assert message.content == "Alert content"
        assert message.url == "https://example.com"
        assert message.change_type == "text"

    def test_alert_message_to_dict(self):
        message = AlertMessage(
            title="Test Alert",
            content="Alert content",
            metadata={"key": "value"},
        )
        data = message.to_dict()
        assert data["title"] == "Test Alert"
        assert data["content"] == "Alert content"
        assert data["metadata"] == {"key": "value"}


class TestAlertChannels:
    """Test alert channel classes."""

    def test_alert_channel_base_class(self):
        channel = AlertChannel()
        with pytest.raises(NotImplementedError):
            channel.send(AlertMessage(title="test", content="test"))

    def test_webhook_alert_creation(self):
        alert = WebhookAlert(webhook_url="https://example.com/webhook")
        assert alert.webhook_url == "https://example.com/webhook"
        assert "Content-Type" in alert.headers

    def test_webhook_alert_with_custom_headers(self):
        alert = WebhookAlert(
            webhook_url="https://example.com/webhook",
            headers={"Authorization": "Bearer token"},
        )
        assert alert.headers["Authorization"] == "Bearer token"

    def test_email_alert_creation(self):
        alert = EmailAlert(
            smtp_server="smtp.example.com",
            smtp_port=587,
            username="user@example.com",
            password="password",
            from_addr="user@example.com",
            to_addrs=["recipient@example.com"],
        )
        assert alert.smtp_server == "smtp.example.com"
        assert alert.smtp_port == 587
        assert alert.username == "user@example.com"
        assert alert.to_addrs == ["recipient@example.com"]
        assert alert.use_tls is True

    def test_dingtalk_alert_creation(self):
        alert = DingTalkAlert(webhook_url="https://oapi.dingtalk.com/robot/send?access_token=test")
        assert alert.webhook_url == "https://oapi.dingtalk.com/robot/send?access_token=test"
        assert alert.secret == ""

    def test_dingtalk_alert_with_secret(self):
        alert = DingTalkAlert(
            webhook_url="https://oapi.dingtalk.com/robot/send?access_token=test",
            secret="test-secret",
        )
        assert alert.secret == "test-secret"

    def test_wecom_alert_creation(self):
        alert = WeComAlert(webhook_url="https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=test")
        assert alert.webhook_url == "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=test"


class TestWebMonitor:
    """Test WebMonitor class."""

    def test_monitor_creation(self):
        config = MonitorConfig()
        monitor = WebMonitor(config=config)
        assert monitor.config == config

    def test_monitor_with_default_config(self):
        monitor = WebMonitor()
        assert monitor.config.check_interval == 300

    def test_add_alert_channel(self):
        monitor = WebMonitor()
        alert = WebhookAlert(webhook_url="https://example.com/webhook")
        monitor.add_alert_channel(alert)
        assert len(monitor._alert_channels) == 1

    def test_compute_hash(self):
        monitor = WebMonitor()
        hash1 = monitor._compute_hash("test content")
        hash2 = monitor._compute_hash("test content")
        hash3 = monitor._compute_hash("different content")
        assert hash1 == hash2
        assert hash1 != hash3

    def test_generate_diff(self):
        monitor = WebMonitor()
        old = "line1\nline2\nline3"
        new = "line1\nline2 modified\nline3\nline4"
        diff = monitor._generate_diff(old, new)
        assert "line2 modified" in diff
        assert "line4" in diff

    def test_generate_diff_truncation(self):
        config = MonitorConfig(max_diff_length=10)
        monitor = WebMonitor(config=config)
        old = "a" * 100
        new = "b" * 100
        diff = monitor._generate_diff(old, new)
        assert len(diff) <= 10 + len("\n... (truncated)")

    def test_get_history_empty(self):
        monitor = WebMonitor()
        history = monitor.get_history("https://example.com")
        assert history == []

    def test_get_all_history_empty(self):
        monitor = WebMonitor()
        history = monitor.get_all_history()
        assert history == {}

    def test_clear_history(self):
        monitor = WebMonitor()
        monitor._history["https://example.com"] = [
            ChangeRecord(url="https://example.com", timestamp="2024-01-01", change_type="text")
        ]
        monitor.clear_history("https://example.com")
        assert "https://example.com" not in monitor._history

    def test_clear_all_history(self):
        monitor = WebMonitor()
        monitor._history["https://example.com"] = [
            ChangeRecord(url="https://example.com", timestamp="2024-01-01", change_type="text")
        ]
        monitor.clear_history()
        assert monitor._history == {}

    def test_get_stats(self):
        monitor = WebMonitor()
        stats = monitor.get_stats()
        assert "monitored_urls" in stats
        assert "total_changes" in stats
        assert "alert_channels" in stats
        assert "check_interval" in stats
        assert stats["monitored_urls"] == 0
        assert stats["total_changes"] == 0
        assert stats["alert_channels"] == 0


class TestUtilityFunctions:
    """Test utility functions."""

    def test_is_monitor_available(self):
        result = is_monitor_available()
        assert result is True
