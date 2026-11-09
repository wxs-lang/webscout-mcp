"""URL-schema resolution for notification targets.

The eight channels each need their own constructor, and `EmailAlert` alone takes seven
arguments. A tool schema cannot reasonably expose that, so `alert_targets` resolves one
URL string into a channel instance - the approach Apprise uses to make dozens of
services addressable by a single parameter.

These tests pin the mapping for every scheme and the error behaviour for malformed
targets. Error messages matter here: a caller that mistypes a scheme should learn what
is valid, not receive a silent no-op.
"""

from __future__ import annotations

import pytest

from webscout_mcp.extras.alert_channels import (
    DingTalkAlert,
    EmailAlert,
    FeishuAlert,
    ServerChanAlert,
    SlackAlert,
    TelegramAlert,
    WebhookAlert,
    WeComAlert,
)
from webscout_mcp.extras.alert_targets import (
    SUPPORTED_SCHEMES,
    build_channel,
    describe_schemes,
)

# --- every scheme maps to its channel --------------------------------


@pytest.mark.parametrize(
    ("target", "expected_type", "expected_name"),
    [
        ("webhook://example.com/hook", WebhookAlert, "webhook"),
        ("dingtalk://oapi.dingtalk.com/robot/send?access_token=ABC", DingTalkAlert, "dingtalk"),
        ("wecom://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=K", WeComAlert, "wecom"),
        ("feishu://open.feishu.cn/HOOK", FeishuAlert, "feishu"),
        ("slack://hooks.slack.com/services/T/B/X", SlackAlert, "slack"),
        ("telegram://TOKEN@CHAT", TelegramAlert, "telegram"),
        ("serverchan://KEY", ServerChanAlert, "serverchan"),
        ("smtp://u:p@smtp.example.com:587?to=a@b.c", EmailAlert, "email"),
    ],
)
def test_scheme_maps_to_channel(target, expected_type, expected_name):
    channel = build_channel(target)
    assert isinstance(channel, expected_type)
    assert channel.name == expected_name
    assert channel.enabled is True


def test_supported_schemes_are_listed():
    assert set(SUPPORTED_SCHEMES) == {
        "webhook",
        "dingtalk",
        "wecom",
        "feishu",
        "slack",
        "telegram",
        "serverchan",
        "smtp",
    }


def test_every_scheme_has_a_description_entry():
    described = {entry["scheme"] for entry in describe_schemes()}
    assert described == set(SUPPORTED_SCHEMES)


# --- credentials and options -----------------------------------------


def test_webhook_preserves_host_and_path():
    channel = build_channel("webhook://hooks.example.com/services/abc")
    assert channel.webhook_url == "https://hooks.example.com/services/abc"


def test_dingtalk_secret_is_read_from_query():
    channel = build_channel("dingtalk://oapi.dingtalk.com/robot/send?access_token=T&secret=S")
    assert "access_token=T" in channel.webhook_url
    assert channel.secret == "S"


def test_smtp_reads_multiple_recipients_and_port():
    channel = build_channel("smtp://user:pass@smtp.example.com:2525?to=a@b.c&to=d@e.f")
    assert channel.smtp_port == 2525
    assert channel.to_addrs == ["a@b.c", "d@e.f"]
    assert channel.smtp_server == "smtp.example.com"


def test_smtp_tls_can_be_disabled():
    channel = build_channel("smtp://u:p@host:25?to=a@b.c&tls=false")
    assert channel.use_tls is False


def test_telegram_splits_token_and_chat():
    channel = build_channel("telegram://123456:ABC-DEF@-1001234567890")
    assert channel.bot_token == "123456:ABC-DEF"
    assert channel.chat_id == "-1001234567890"


def test_percent_encoded_credentials_are_decoded():
    channel = build_channel("smtp://user%40domain:p%40ss@host:587?to=a@b.c")
    assert channel.username == "user@domain"
    assert channel.password == "p@ss"


# --- error behaviour --------------------------------------------------


def test_empty_target_is_rejected():
    with pytest.raises(ValueError, match="empty"):
        build_channel("")


def test_unknown_scheme_lists_the_valid_ones():
    with pytest.raises(ValueError) as excinfo:
        build_channel("ftp://example.com/x")
    message = str(excinfo.value)
    assert "ftp" in message
    for scheme in SUPPORTED_SCHEMES:
        assert scheme in message, f"{scheme} missing from the error message"


def test_telegram_without_chat_id_is_rejected():
    with pytest.raises(ValueError, match="CHAT_ID"):
        build_channel("telegram://nohost")


def test_dingtalk_without_token_is_rejected():
    with pytest.raises(ValueError, match="access_token"):
        build_channel("dingtalk://oapi.dingtalk.com/robot/send")


def test_wecom_without_key_is_rejected():
    with pytest.raises(ValueError, match="key"):
        build_channel("wecom://qyapi.weixin.qq.com/cgi-bin/webhook/send")


def test_smtp_without_recipient_is_rejected():
    with pytest.raises(ValueError, match="to="):
        build_channel("smtp://u:p@host:587")


def test_smtp_without_host_is_rejected():
    with pytest.raises(ValueError):
        build_channel("smtp://?to=a@b.c")


def test_scheme_matching_is_case_insensitive():
    """URLs are case-insensitive in the scheme; a caller may shout."""
    channel = build_channel("WEBHOOK://example.com/hook")
    assert isinstance(channel, WebhookAlert)
