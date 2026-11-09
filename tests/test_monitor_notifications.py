"""Notification delivery from web_monitor.

Getting a change to actually arrive required fixing three defects in series, each hidden
by the one before it:

1. `monitor._send_alerts` built `AlertMessage(change_type=...)` - this module's own
   dataclass - and passed it to a channel, which reads `message.level`. But
   `alert_channels.AlertMessage` is a *different* dataclass with `level` instead of
   `change_type` and a float instead of ISO timestamp. The send raised AttributeError,
   caught by the per-channel try/except and logged.

2. Because that exception was swallowed, delivery looked fine. `_send_alerts` returned
   nothing, so the caller could not tell a delivered alert from a failed one.

3. Once delivery results were surfaced, the first real attempt failed with
   `SSL: WRONG_VERSION_NUMBER` in seconds: `webhook://` always rebuilt as https, so any
   local or internal http endpoint was unreachable.

A test per defect, plus the end-to-end path.
"""

from __future__ import annotations

import http.server
import json
import pathlib
import tempfile
import threading

import pytest

import webscout_mcp.extras.monitor as monitor_mod
from webscout_mcp.extras.alert_channels import AlertMessage as ChannelMessage
from webscout_mcp.extras.alert_targets import build_channel
from webscout_mcp.extras.monitor import AlertMessage as MonitorMessage
from webscout_mcp.extras.monitor import ChangeRecord, MonitorConfig, WebMonitor

PAGE_A = '<html><body><p>Body.</p><span class="price">$100.00</span></body></html>'
PAGE_B = '<html><body><p>Body.</p><span class="price">$900.00</span></body></html>'


class _Response:
    def __init__(self, html: str) -> None:
        self.content = html
        self.html = html


class _Fetcher:
    def __init__(self, holder: dict) -> None:
        self._holder = holder

    def fetch(self, url: str, **kwargs) -> _Response:
        return _Response(self._holder["html"])


def _record() -> ChangeRecord:
    return ChangeRecord(
        url="https://x.test/page",
        timestamp="2026-11-01T10:00:00",
        change_type="price",
        old_value="100",
        new_value="900",
        diff="100 -> 900",
        metadata={"change_pct": 8.0},
    )


# --- defect 1: the two AlertMessage classes ---------------------------


def test_the_two_alert_message_classes_have_different_fields():
    """Naming them the same is what made the mismatch invisible."""
    import dataclasses

    monitor_fields = {f.name for f in dataclasses.fields(MonitorMessage)}
    channel_fields = {f.name for f in dataclasses.fields(ChannelMessage)}
    assert "change_type" in monitor_fields and "change_type" not in channel_fields
    assert "level" in channel_fields and "level" not in monitor_fields
    assert MonitorMessage is not ChannelMessage


def test_conversion_produces_a_channel_compatible_message():
    """The adapter that makes a send possible at all."""
    source = MonitorMessage(
        title="t",
        content="c",
        url="https://x.test/",
        change_type="price",
        timestamp="2026-11-01T10:00:00",
        metadata={"k": "v"},
    )
    converted = monitor_mod._to_channel_message(_record(), source)
    assert isinstance(converted, ChannelMessage)
    assert converted.level == "info"
    assert isinstance(converted.timestamp, float)
    assert converted.metadata["change_type"] == "price"


def test_channel_formats_a_converted_message_without_raising():
    converted = monitor_mod._to_channel_message(
        _record(),
        MonitorMessage(title="t", content="c", url="u", change_type="text", timestamp="2026-11-01T10:00:00"),
    )
    text = build_channel("webhook://example.com/x").format_message(converted)
    assert "t" in text and "c" in text


# --- defect 2: delivery results were discarded ------------------------


class _Sink(http.server.BaseHTTPRequestHandler):
    received: list[dict] = []

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode("utf-8", errors="replace")
        _Sink.received.append({"path": self.path, "body": body})
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"ok":true}')

    def log_message(self, *args):
        pass


@pytest.fixture
def sink_server():
    _Sink.received = []
    httpd = http.server.HTTPServer(("127.0.0.1", 0), _Sink)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield httpd.server_address[1]
    finally:
        httpd.shutdown()


def test_send_alerts_returns_one_outcome_per_channel(sink_server):
    holder = {"html": PAGE_A}
    config = MonitorConfig(
        history_path=str(pathlib.Path(tempfile.mkdtemp()) / "s.json"),
        price_selector="span.price",
        min_change_size=5,
    )
    monitor = WebMonitor(config=config, fetcher=_Fetcher(holder))
    monitor.add_alert_channel(build_channel(f"webhook://127.0.0.1:{sink_server}/hook"))

    monitor.check_url("https://x.test/page")
    holder["html"] = PAGE_B
    monitor.check_url("https://x.test/page")

    delivery = monitor.last_delivery
    assert delivery, "a detected change must record a delivery attempt"
    assert delivery[0]["success"] is True
    assert delivery[0]["message"] == "HTTP 200"


def test_a_failing_channel_is_reported_not_hidden():
    holder = {"html": PAGE_A}
    config = MonitorConfig(
        history_path=str(pathlib.Path(tempfile.mkdtemp()) / "s.json"),
        price_selector="span.price",
        min_change_size=5,
    )
    monitor = WebMonitor(config=config, fetcher=_Fetcher(holder))
    # port 1 refuses connections; the failure must appear rather than be swallowed
    monitor.add_alert_channel(build_channel("webhook://127.0.0.1:1/hook"))

    monitor.check_url("https://x.test/page")
    holder["html"] = PAGE_B
    monitor.check_url("https://x.test/page")

    assert monitor.last_delivery
    assert monitor.last_delivery[0]["success"] is False
    assert monitor.last_delivery[0]["error"]


# --- defect 3: webhook scheme forced to https -------------------------


def test_loopback_webhook_uses_http():
    assert build_channel("webhook://127.0.0.1:8080/hook").webhook_url.startswith("http://")


def test_localhost_webhook_uses_http():
    assert build_channel("webhook://localhost:9000/x").webhook_url.startswith("http://")


def test_public_webhook_defaults_to_https():
    assert build_channel("webhook://example.com/hook").webhook_url.startswith("https://")


def test_http_can_be_forced_on_a_public_host():
    assert build_channel("webhook://example.com/hook?http=1").webhook_url.startswith("http://")


# --- end to end through the tool --------------------------------------


def _payload(result) -> dict:
    obj = result[0] if isinstance(result, tuple) else result
    content = getattr(obj, "content", obj)
    block = content[0] if isinstance(content, list) else content
    return json.loads(getattr(block, "text", str(block)))


def test_tool_delivers_a_change_and_reports_success(monkeypatch, sink_server, tmp_path):
    import asyncio

    from webscout_mcp.server import create_server

    holder = {"html": PAGE_A}
    original = monitor_mod.WebMonitor.__init__

    def patched(self, config=None, fetcher=None):
        original(self, config=config, fetcher=_Fetcher(holder))

    monkeypatch.setattr(monitor_mod.WebMonitor, "__init__", patched)

    args = {
        "url": "https://x.test/page",
        "state_path": str(tmp_path / "state.json"),
        "price_selector": "span.price",
        "min_change_size": 5,
        "notify": [f"webhook://127.0.0.1:{sink_server}/hook"],
    }

    async def run_once():
        server = create_server()
        return _payload(await server.call_tool("web_monitor", args))

    first = asyncio.run(run_once())
    assert first["change_count"] == 0
    assert first["notifications"]["delivery"] == []

    holder["html"] = PAGE_B
    second = asyncio.run(run_once())
    assert second["change_count"] >= 1
    delivery = second["notifications"]["delivery"]
    assert delivery and delivery[0]["success"] is True
    assert _Sink.received, "the webhook must actually be called"
    assert "900" in _Sink.received[-1]["body"]


def test_bad_target_is_reported_and_others_still_used(monkeypatch, sink_server, tmp_path):
    import asyncio

    from webscout_mcp.server import create_server

    holder = {"html": PAGE_A}
    original = monitor_mod.WebMonitor.__init__

    def patched(self, config=None, fetcher=None):
        original(self, config=config, fetcher=_Fetcher(holder))

    monkeypatch.setattr(monitor_mod.WebMonitor, "__init__", patched)

    args = {
        "url": "https://x.test/page",
        "state_path": str(tmp_path / "state.json"),
        "price_selector": "span.price",
        "min_change_size": 5,
        "notify": ["nonsense://x/y", f"webhook://127.0.0.1:{sink_server}/hook"],
    }

    async def run_once():
        server = create_server()
        return _payload(await server.call_tool("web_monitor", args))

    asyncio.run(run_once())
    holder["html"] = PAGE_B
    out = asyncio.run(run_once())

    assert out["notifications"]["errors"], "the bad target must be reported"
    assert out["notifications"]["delivery"][0]["success"] is True, "the good target must still fire"


def test_credentials_are_not_echoed_in_the_response(monkeypatch, tmp_path):
    import asyncio

    from webscout_mcp.server import create_server

    holder = {"html": PAGE_A}
    original = monitor_mod.WebMonitor.__init__

    def patched(self, config=None, fetcher=None):
        original(self, config=config, fetcher=_Fetcher(holder))

    monkeypatch.setattr(monitor_mod.WebMonitor, "__init__", patched)

    async def go():
        server = create_server()
        return _payload(
            await server.call_tool(
                "web_monitor",
                {
                    "url": "https://x.test/page",
                    "state_path": str(tmp_path / "state.json"),
                    "notify": ["telegram://SECRET_TOKEN@CHAT"],
                },
            )
        )

    out = asyncio.run(go())
    assert "SECRET_TOKEN" not in json.dumps(out)
