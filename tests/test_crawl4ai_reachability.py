"""Tests for Crawl4AI sidecar reachability.

The defect these cover: ``is_available`` returned ``enabled`` - "a sidecar is
configured" - while its docstring promised "configured and reachable". With
``crawl4ai_enabled=true`` and a ``base_url`` pointing at a sidecar that was not
running, the backend was still registered as a BROWSER provider, so every
SPA-shaped page paid a real round trip to a service that did not exist. The
fetch then fell back and preserved the content, so nothing looked broken while
the latency was wasted on every such request.

Measured before the fix: a real fetch of a 3957-char page took 8387ms on the
first call, with ``browser_attempted=True`` and ``browser_success=False``. After
it: 260ms with ``browser_attempted=False``.
"""

from __future__ import annotations

import socket
import time

import pytest

from webscout_mcp import crawl4ai_backend
from webscout_mcp.config import Config
from webscout_mcp.crawl4ai_backend import Crawl4AIBrowserBackend, _is_fake_ip, _tcp_reachable
from webscout_mcp.provider_router import ProviderCapability


def _backend(enabled: bool = True, base_url: str = "http://127.0.0.1:1") -> Crawl4AIBrowserBackend:
    cfg = Config()
    cfg.crawl4ai_enabled = enabled
    cfg.crawl4ai_base_url = base_url
    return Crawl4AIBrowserBackend(cfg)


@pytest.fixture
def listening_port():
    """A real listening socket, so 'reachable' can be exercised without a service."""
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", 0))
    # Backlog above 1: the probe opens a connection and walks away without
    # accepting, so a single-slot queue would refuse later probes.
    srv.listen(16)
    port = srv.getsockname()[1]
    try:
        yield port
    finally:
        srv.close()


# --- Configuration vs reachability are now distinct ---------------------


def test_is_configured_is_true_for_a_configured_but_dead_sidecar():
    """The old is_available returned exactly this. It is not availability."""
    b = _backend(enabled=True, base_url="http://127.0.0.1:1")
    assert b.is_configured is True


def test_is_available_is_false_when_the_sidecar_is_not_listening():
    b = _backend(enabled=True, base_url="http://127.0.0.1:1")
    assert b.is_available is False


def test_is_configured_and_is_available_agree_only_when_reachable(listening_port):
    b = _backend(enabled=True, base_url=f"http://127.0.0.1:{listening_port}")
    assert b.is_configured is True
    assert b.is_available is True


def test_disabled_backend_is_neither_configured_nor_available():
    b = _backend(enabled=False, base_url="http://127.0.0.1:1")
    assert b.is_configured is False
    assert b.is_available is False


def test_missing_base_url_means_not_configured():
    b = _backend(enabled=True, base_url="")
    assert b.is_configured is False
    assert b.is_available is False


# --- The probe must be bounded and memoised ----------------------------


def test_probe_is_memoised():
    """Registration must not re-probe; a dead sidecar must not cost per request."""
    b = _backend(base_url="http://127.0.0.1:1")
    assert b.is_available is False
    start = time.perf_counter()
    for _ in range(20):
        assert b.is_available is False
    elapsed_ms = (time.perf_counter() - start) * 1000
    assert elapsed_ms < 50, f"20 cached reads took {elapsed_ms:.0f}ms; probe is not memoised"


def test_probe_respects_its_budget():
    """A timeout is a total budget, not a per-address one.

    httpx applied its timeout per resolved address, so localhost (::1 then
    127.0.0.1) took 3509ms against a 1.5s timeout on this host, which silently
    drops the SYN instead of refusing it. The connect loop walks addresses under
    one deadline.
    """
    start = time.perf_counter()
    reachable = _tcp_reachable("http://127.0.0.1:1", timeout=0.3)
    elapsed_ms = (time.perf_counter() - start) * 1000
    assert reachable is False
    assert elapsed_ms < 600, f"probe overran its 0.3s budget: {elapsed_ms:.0f}ms"


def test_probe_detects_a_real_listener(listening_port):
    assert _tcp_reachable(f"http://127.0.0.1:{listening_port}", timeout=1.0) is True


def test_probe_handles_a_https_url(listening_port):
    """Scheme decides the default port; an explicit port still wins."""
    assert _tcp_reachable(f"https://127.0.0.1:{listening_port}", timeout=1.0) is True


def test_probe_returns_false_for_unparseable_input():
    assert _tcp_reachable("", timeout=0.2) is False
    assert _tcp_reachable("not-a-url", timeout=0.2) is False


def test_probe_rejects_fake_ip_answers():
    """A proxy in TUN mode answers for every name, including reserved ones.

    On this host ``this-host-does-not-exist.invalid`` resolves to 198.18.0.60
    and the proxy accepts the connection, so a naive probe would report the
    sidecar reachable. That range is rejected explicitly.
    """
    assert _tcp_reachable("http://this-host-does-not-exist.invalid:1", timeout=0.3) is False


def test_fake_ip_detection_covers_the_benchmarking_range():
    assert _is_fake_ip("198.18.0.60") is True
    assert _is_fake_ip("198.19.255.1") is True
    assert _is_fake_ip("127.0.0.1") is False
    assert _is_fake_ip("10.0.0.5") is False
    assert _is_fake_ip("not-an-ip") is False


def test_localhost_is_still_a_valid_sidecar_target():
    """Rejecting fake-IP must not break the normal localhost deployment."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as srv:
        srv.bind(("127.0.0.1", 0))
        srv.listen(1)
        port = srv.getsockname()[1]
        assert _tcp_reachable(f"http://127.0.0.1:{port}", timeout=1.0) is True


# --- Registration behaviour -------------------------------------------


def test_unreachable_backend_is_not_registered():
    """The end-to-end consequence: nothing registers, so nothing can escalate.

    ``registry.select`` returns a name from the router's configured list whether
    or not the provider was registered, so it is the wrong assertion here. What
    matters is that the ``if backend.is_available`` gate that eval_services and
    server.py both use now says no.
    """
    from webscout_mcp.provider_registry import ProviderRegistry

    reg = ProviderRegistry()
    b = _backend(enabled=True, base_url="http://127.0.0.1:1")

    # This mirrors eval_services:151 and server.py:129.
    if b.is_available:
        reg.register(b, capabilities={ProviderCapability.BROWSER})

    assert b.is_available is False
    assert b.is_configured is True, "it is configured; it just is not running"
    assert reg.select(ProviderCapability.BROWSER) is None


def test_logs_a_warning_when_configured_but_unreachable(caplog):
    """Silently disabling escalation would be its own support burden."""
    with caplog.at_level("WARNING"):
        b = _backend(enabled=True, base_url="http://127.0.0.1:1")
        assert b.is_available is False
    messages = [r.getMessage() for r in caplog.records]
    assert any("not reachable" in m for m in messages), messages


def test_module_timeout_constant_is_small():
    """It runs at registration; startup must not wait on a dead sidecar."""
    assert crawl4ai_backend._PROBE_CONNECT_TIMEOUT <= 1.0
