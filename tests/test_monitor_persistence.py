"""web_monitor: state must survive between calls, or the tool cannot detect anything.

## The defect this file exists for

`_save_history` stored only the change log, and `check_url` called it only inside
`if changes:`. So the first check for a URL - which by definition reports nothing -
persisted no baseline. Every subsequent process started empty.

Observed through the tool: three consecutive calls each built a fresh `WebMonitor`, so
the second call, after the page had genuinely changed, returned 0 changes. A monitoring
tool that forgets what it saw is not a monitoring tool.

Fixed twice over: the baseline now goes into the state file under `__baseline__`, and
the save happens whenever the baseline moved rather than only when something was
reported.
"""

from __future__ import annotations

import json
import pathlib
import tempfile

import pytest

import webscout_mcp.extras.monitor as monitor_mod
from webscout_mcp.extras.monitor import MonitorConfig, WebMonitor

PAGE_V1 = """<html><body>
<p>Stable article about scraping.</p>
<span class="price">$100.00</span>
<p>Rendered at 2026-11-01T10:00:00 session abc</p>
<div class="ad">AD-A 111</div>
</body></html>"""

PAGE_V2 = """<html><body>
<p>Stable article about scraping.</p>
<span class="price">$900.00</span>
<p>Rendered at 2026-11-01T11:30:00 session xyz</p>
<div class="ad">AD-B 999</div>
</body></html>"""

PAGE_V3 = """<html><body>
<p>The article body was rewritten to mention rendering.</p>
<span class="price">$900.00</span>
<p>Rendered at 2026-11-01T12:00:00 session qqq</p>
<div class="ad">AD-C 555</div>
</body></html>"""

FILTERS = {
    "price_selector": "span.price",
    "ignore_selector": [".ad"],
    "ignore_text": [r"Rendered at \S+ session \w+"],
    "min_change_size": 5,
}


class _Response:
    def __init__(self, html: str) -> None:
        self.content = html
        self.html = html


class _Fetcher:
    def __init__(self, holder: dict) -> None:
        self._holder = holder

    def fetch(self, url: str, **kwargs) -> _Response:
        return _Response(self._holder["html"])


def _new_monitor(state: pathlib.Path, holder: dict, **extra) -> WebMonitor:
    config = MonitorConfig(history_path=str(state), **{**FILTERS, **extra})
    return WebMonitor(config=config, fetcher=_Fetcher(holder))


# --- the persistence defect -------------------------------------------


def test_state_file_is_written_on_the_first_check():
    """The baseline must reach disk even though the first check reports nothing."""
    state = pathlib.Path(tempfile.mkdtemp()) / "state.json"
    holder = {"html": PAGE_V1}
    monitor = _new_monitor(state, holder)
    assert monitor.check_url("https://x.test/page") == []
    assert state.exists(), "a baseline-only check must still persist state"


def test_baseline_is_stored_under_a_reserved_key():
    state = pathlib.Path(tempfile.mkdtemp()) / "state.json"
    holder = {"html": PAGE_V1}
    _new_monitor(state, holder).check_url("https://x.test/page")

    data = json.loads(state.read_text(encoding="utf-8"))
    assert "__baseline__" in data
    entry = data["__baseline__"]["https://x.test/page"]
    assert "text_hash" in entry
    assert entry["price"] == pytest.approx(100.0)


def test_a_second_monitor_instance_detects_the_change():
    """This is the behaviour that was broken: a fresh instance saw nothing."""
    state = pathlib.Path(tempfile.mkdtemp()) / "state.json"
    holder = {"html": PAGE_V1}
    _new_monitor(state, holder).check_url("https://x.test/page")

    holder["html"] = PAGE_V2
    changes = _new_monitor(state, holder).check_url("https://x.test/page")

    kinds = {c.change_type for c in changes}
    assert "price" in kinds, f"expected a price change, got {kinds}"
    assert "text" in kinds, f"expected a text change, got {kinds}"


def test_no_change_reported_on_a_third_identical_check():
    state = pathlib.Path(tempfile.mkdtemp()) / "state.json"
    holder = {"html": PAGE_V1}
    _new_monitor(state, holder).check_url("https://x.test/page")

    holder["html"] = PAGE_V2
    _new_monitor(state, holder).check_url("https://x.test/page")

    assert _new_monitor(state, holder).check_url("https://x.test/page") == []


def test_a_later_edit_is_reported_after_a_quiet_check():
    state = pathlib.Path(tempfile.mkdtemp()) / "state.json"
    holder = {"html": PAGE_V1}
    _new_monitor(state, holder).check_url("https://x.test/page")
    holder["html"] = PAGE_V2
    _new_monitor(state, holder).check_url("https://x.test/page")
    assert _new_monitor(state, holder).check_url("https://x.test/page") == []

    holder["html"] = PAGE_V3
    changes = _new_monitor(state, holder).check_url("https://x.test/page")
    assert [c.change_type for c in changes] == ["text"]


def test_history_records_accumulate_across_instances():
    state = pathlib.Path(tempfile.mkdtemp()) / "state.json"
    holder = {"html": PAGE_V1}
    _new_monitor(state, holder).check_url("https://x.test/page")
    holder["html"] = PAGE_V2
    _new_monitor(state, holder).check_url("https://x.test/page")
    holder["html"] = PAGE_V3
    _new_monitor(state, holder).check_url("https://x.test/page")

    data = json.loads(state.read_text(encoding="utf-8"))
    assert len(data["https://x.test/page"]) >= 2


def test_old_state_file_without_baseline_still_loads():
    """A file written before `__baseline__` existed must not raise."""
    state = pathlib.Path(tempfile.mkdtemp()) / "state.json"
    state.write_text(
        json.dumps(
            {
                "https://x.test/page": [
                    {
                        "url": "https://x.test/page",
                        "timestamp": "2026-11-01T00:00:00",
                        "change_type": "text",
                        "old_value": "a",
                        "new_value": "b",
                        "diff": "",
                        "metadata": {},
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    monitor = _new_monitor(state, {"html": PAGE_V1})
    assert monitor.get_history("https://x.test/page")
    # no baseline means the next check simply establishes one
    assert monitor.check_url("https://x.test/page") == []


def test_state_file_is_readable_after_non_ascii_content():
    """`open()` without an encoding decodes as cp936 on Windows and corrupts this."""
    state = pathlib.Path(tempfile.mkdtemp()) / "state.json"
    holder = {"html": "<html><body><p>中文内容在这里，用于检验编码处理。</p></body></html>"}
    _new_monitor(state, holder).check_url("https://x.test/page")
    holder["html"] = "<html><body><p>中文内容已被改写，用于检验编码处理。</p></body></html>"
    changes = _new_monitor(state, holder).check_url("https://x.test/page")
    assert len(changes) == 1
    assert "中文" in json.loads(state.read_text(encoding="utf-8"))["__baseline__"]["https://x.test/page"]["text"]


# --- tool-level contract ----------------------------------------------


def _payload(result) -> dict:
    obj = result[0] if isinstance(result, tuple) else result
    content = getattr(obj, "content", obj)
    block = content[0] if isinstance(content, list) else content
    return json.loads(getattr(block, "text", str(block)))


@pytest.fixture
def patched_fetcher(monkeypatch):
    holder = {"html": PAGE_V1}
    original = monitor_mod.WebMonitor.__init__

    def patched(self, config=None, fetcher=None):
        original(self, config=config, fetcher=_Fetcher(holder))

    monkeypatch.setattr(monitor_mod.WebMonitor, "__init__", patched)
    return holder


def test_tool_registers_and_counts_fifteen():
    import asyncio

    from webscout_mcp.server import create_server

    tools = asyncio.run(create_server().list_tools())
    names = {t.name for t in tools}
    assert "web_monitor" in names
    assert len(names) == 15, f"tool count changed: {sorted(names)}"


def test_tool_says_it_does_not_schedule_itself():
    import asyncio

    from webscout_mcp.server import create_server

    tools = asyncio.run(create_server().list_tools())
    tool = next(t for t in tools if t.name == "web_monitor")
    desc = (tool.description or "").lower()
    assert "once per call" in desc or "does not schedule" in desc
    assert "baseline" in desc


def test_tool_rejects_an_empty_url():
    import asyncio

    from webscout_mcp.server import create_server

    async def go():
        server = create_server()
        return await server.call_tool("web_monitor", {"url": ""})

    assert "error" in _payload(asyncio.run(go()))


def test_tool_reports_baseline_then_change(patched_fetcher, tmp_path):
    import asyncio

    from webscout_mcp.server import create_server

    state = tmp_path / "state.json"
    args = {"url": "https://x.test/page", "state_path": str(state), **FILTERS}

    async def run_once():
        server = create_server()
        return _payload(await server.call_tool("web_monitor", args))

    first = asyncio.run(run_once())
    assert first["baseline_established"] is True
    assert first["change_count"] == 0

    patched_fetcher["html"] = PAGE_V2
    second = asyncio.run(run_once())
    assert second["change_count"] >= 2
    kinds = {c["change_type"] for c in second["changes"]}
    assert "price" in kinds
