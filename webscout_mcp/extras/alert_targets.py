"""Resolve notification targets from a single URL string.

Every channel in :mod:`alert_channels` needs its own constructor arguments, which makes
them impractical to expose through a tool schema - a caller cannot be expected to
assemble ``EmailAlert(smtp_server, smtp_port, username, password, from_addr, to_addrs,
use_tls)``. A URL encodes destination and credentials in one string, which is how
Apprise makes fifty-plus notification services addressable by one parameter.

Supported schemes::

    webhook://host/path                 generic JSON POST
    dingtalk://host/robot/send?access_token=X&secret=Y
    wecom://host/cgi-bin/webhook/send?key=X
    feishu://host/open-apis/bot/v2/hook/X
    slack://host/services/T/B/X
    telegram://TOKEN@CHAT_ID
    serverchan://SEND_KEY
    smtp://user:pass@host:587?to=a@b.c&to=d@e.f

Unknown schemes raise :class:`ValueError` listing the valid ones, so a caller receives a
fixable error instead of silence. Credentials remain inside the parsed URL and are
never written to logs.
"""

from __future__ import annotations

from urllib.parse import parse_qs, unquote, urlparse

__all__ = ["SUPPORTED_SCHEMES", "build_channel", "describe_schemes"]


def _require(netloc: str, scheme: str) -> str:
    if not netloc:
        raise ValueError(f"{scheme}:// target is missing a host")
    return netloc


def _build_webhook(parts) -> object:
    from .alert_channels import WebhookAlert

    host = _require(parts.netloc, "webhook")
    # The scheme of a `webhook://` URL says nothing about transport, so default to https
    # and let `?http=1` (or a loopback host) opt into plain HTTP. Forcing https broke
    # local and internal endpoints with an SSL "wrong version number" error, which is
    # confusing because the server is fine.
    query = {k.lower(): v for k, v in parse_qs(parts.query).items()}
    host_only = (parts.hostname or "").lower()
    loopback = host_only in ("localhost", "127.0.0.1", "::1") or host_only.startswith("127.")
    force_http = (query.get("http") or ["0"])[0].lower() in ("1", "true", "yes")
    scheme = "http" if (force_http or loopback) else "https"

    suffix = ""
    if parts.query and not force_http:
        # preserve other query parameters (tokens etc.) on the rebuilt URL
        kept = {k: v[0] for k, v in parse_qs(parts.query).items() if k.lower() not in ("http",)}
        if kept:
            from urllib.parse import urlencode

            suffix = "?" + urlencode(kept)

    return WebhookAlert(webhook_url=f"{scheme}://{host}{parts.path}{suffix}")


def _build_dingtalk(parts) -> object:
    from .alert_channels import DingTalkAlert

    host = _require(parts.netloc, "dingtalk")
    query = parse_qs(parts.query)
    token = (query.get("access_token") or [""])[0]
    secret = (query.get("secret") or [None])[0]
    if not token:
        raise ValueError("dingtalk:// target needs an access_token query parameter")
    return DingTalkAlert(webhook_url=f"https://{host}/robot/send?access_token={token}", secret=secret)


def _build_wecom(parts) -> object:
    from .alert_channels import WeComAlert

    host = _require(parts.netloc, "wecom")
    key = (parse_qs(parts.query).get("key") or [""])[0]
    if not key:
        raise ValueError("wecom:// target needs a key query parameter")
    return WeComAlert(webhook_url=f"https://{host}/cgi-bin/webhook/send?key={key}")


def _build_feishu(parts) -> object:
    from .alert_channels import FeishuAlert

    host = _require(parts.netloc, "feishu")
    path = parts.path.lstrip("/")
    if not path:
        raise ValueError("feishu:// target needs a webhook path")
    return FeishuAlert(webhook_url=f"https://{host}/open-apis/bot/v2/hook/{path}")


def _build_slack(parts) -> object:
    from .alert_channels import SlackAlert

    host = _require(parts.netloc, "slack")
    path = parts.path.lstrip("/")
    if not path:
        raise ValueError("slack:// target needs a webhook path")
    channel = (parse_qs(parts.query).get("channel") or [None])[0]
    return SlackAlert(webhook_url=f"https://{host}/{path}", channel=channel)


def _build_telegram(parts) -> object:
    from .alert_channels import TelegramAlert

    # A Telegram bot token contains a colon ("123456:ABC-DEF"), which urlparse reads
    # as a user:password separator - parts.username would yield only "123456" and the
    # token would fail authentication. Split the netloc by hand at the last "@".
    netloc = parts.netloc or ""
    if "@" not in netloc:
        raise ValueError("telegram:// target must look like telegram://TOKEN@CHAT_ID")
    token, _, chat_id = netloc.rpartition("@")
    if not token or not chat_id:
        raise ValueError("telegram:// target must look like telegram://TOKEN@CHAT_ID")
    return TelegramAlert(bot_token=unquote(token), chat_id=chat_id.strip("/"))


def _build_serverchan(parts) -> object:
    from .alert_channels import ServerChanAlert

    key = (parts.netloc or parts.path.lstrip("/")).strip("/")
    if not key:
        raise ValueError("serverchan:// target needs a send key")
    return ServerChanAlert(send_key=key)


def _build_smtp(parts) -> object:
    from .alert_channels import EmailAlert

    host = _require(parts.hostname or "", "smtp")
    query = parse_qs(parts.query)
    recipients = query.get("to") or []
    if not recipients:
        raise ValueError("smtp:// target needs at least one ?to= address")
    username = unquote(parts.username or "")
    password = unquote(parts.password or "")
    from_addr = (query.get("from") or [username])[0]
    if not from_addr:
        raise ValueError("smtp:// target needs a from address (user@host or ?from=)")
    port = int(parts.port or 587)
    use_tls = (query.get("tls") or ["true"])[0].lower() not in ("0", "false", "no")
    return EmailAlert(
        smtp_server=host,
        smtp_port=port,
        username=username,
        password=password,
        from_addr=from_addr,
        to_addrs=list(recipients),
        use_tls=use_tls,
    )


_SUPPORTED = {
    "webhook": _build_webhook,
    "dingtalk": _build_dingtalk,
    "wecom": _build_wecom,
    "feishu": _build_feishu,
    "slack": _build_slack,
    "telegram": _build_telegram,
    "serverchan": _build_serverchan,
    "smtp": _build_smtp,
}

SUPPORTED_SCHEMES: tuple[str, ...] = tuple(sorted(_SUPPORTED))


def describe_schemes() -> list[dict[str, str]]:
    """One entry per scheme, for putting in a tool description or an error message."""
    return [
        {"scheme": "webhook", "example": "webhook://example.com/hook", "note": "generic JSON POST"},
        {
            "scheme": "dingtalk",
            "example": "dingtalk://oapi.dingtalk.com/robot/send?access_token=X&secret=Y",
            "note": "optional secret enables signed requests",
        },
        {
            "scheme": "wecom",
            "example": "wecom://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=X",
            "note": "WeCom group robot",
        },
        {"scheme": "feishu", "example": "feishu://open.feishu.cn/HOOK_PATH", "note": "Feishu/Lark bot"},
        {"scheme": "slack", "example": "slack://hooks.slack.com/services/T/B/X", "note": "Slack incoming webhook"},
        {"scheme": "telegram", "example": "telegram://BOT_TOKEN@CHAT_ID", "note": "token before @, chat id after"},
        {"scheme": "serverchan", "example": "serverchan://SEND_KEY", "note": "ServerChan push"},
        {
            "scheme": "smtp",
            "example": "smtp://user:pass@smtp.example.com:587?to=a@b.c",
            "note": "one or more ?to= recipients",
        },
    ]


def build_channel(target: str):
    """Build a channel instance from a single URL string.

    Args:
        target: e.g. ``webhook://example.com/hook`` or ``telegram://TOKEN@CHAT``.

    Returns:
        A :class:`~webscout_mcp.extras.alert_channels.BaseAlertChannel` subclass instance.

    Raises:
        ValueError: if the scheme is unknown or required parts are missing. The message
            lists the valid schemes so the caller can correct the input.
    """
    if not target or not target.strip():
        raise ValueError("empty notification target")

    parts = urlparse(target.strip())
    builder = _SUPPORTED.get(parts.scheme.lower())
    if builder is None:
        raise ValueError(f"unsupported notification scheme {parts.scheme!r}. Supported: {', '.join(SUPPORTED_SCHEMES)}")
    return builder(parts)
