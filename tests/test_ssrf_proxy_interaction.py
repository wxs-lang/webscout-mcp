"""Regression tests for the SSRF/proxy interaction the agent simulation found.

The defect: with a proxy configured, every legitimate URL was refused because
the guard resolved locally (getting transparent-proxy fake-IPs) while httpx
sends the hostname to the proxy for remote resolution. `web_fetch` returned
0 characters and an "SSRF blocked" message, which reads to an agent as a
security refusal rather than a configuration mismatch.

These tests pin the boundary so a future "make it work with proxies" change
cannot quietly turn the guard off:

  - fake-IP + proxy        -> allowed (the proxy resolves; this address is
                              never contacted)
  - fake-IP, no proxy      -> refused (the local answer IS the address that
                              would be dialled)
  - real private + proxy   -> refused (a proxy does not make an internal
                              target safe)
  - literal private IP     -> refused regardless of proxy

They manipulate os.environ directly and restore it, because the product reads
the proxy variables at check time (httpx reads them at client construction).
"""

from __future__ import annotations

import os

import pytest

from webscout_mcp.security import url_safety

PROXY_VARS = ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy")


@pytest.fixture
def no_proxy_env(monkeypatch):
    for v in PROXY_VARS:
        monkeypatch.delenv(v, raising=False)


@pytest.fixture
def proxy_env(monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:7890")
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:7890")


@pytest.fixture
def fake_ip_dns(monkeypatch):
    """Make resolution return a transparent-proxy placeholder."""
    monkeypatch.setattr(url_safety, "_resolve_host", lambda host: ["198.18.1.45"])


@pytest.fixture
def private_dns(monkeypatch):
    monkeypatch.setattr(url_safety, "_resolve_host", lambda host: ["10.0.0.5"])


def test_fake_ip_with_proxy_is_allowed(fake_ip_dns, proxy_env):
    """The fix: a placeholder answer behind a proxy is not a safety verdict."""
    res = url_safety.check_url_safe("https://docs.python.org/")
    assert res.safe is True
    assert "proxy resolves" in res.reason


def test_fake_ip_without_proxy_is_refused(fake_ip_dns, no_proxy_env):
    """Without a proxy the local answer is the address that gets dialled."""
    res = url_safety.check_url_safe("https://docs.python.org/")
    assert res.safe is False
    assert "non-public" in res.reason


def test_real_private_address_with_proxy_is_refused(private_dns, proxy_env):
    """The exemption must not widen: a proxy does not make an internal target safe."""
    res = url_safety.check_url_safe("http://internal.corp/")
    assert res.safe is False
    assert "non-public" in res.reason


def test_literal_private_ip_is_refused_with_proxy(proxy_env):
    for url in ("http://127.0.0.1:8080/", "http://10.0.0.5/", "http://169.254.169.254/latest/meta-data/"):
        res = url_safety.check_url_safe(url)
        assert res.safe is False, f"{url} must stay blocked even with a proxy"


def test_mixed_answers_are_refused(monkeypatch, proxy_env):
    """One real private address among placeholders keeps the URL blocked."""
    monkeypatch.setattr(url_safety, "_resolve_host", lambda host: ["198.18.1.45", "10.0.0.5"])
    res = url_safety.check_url_safe("https://mixed.example/")
    assert res.safe is False


def test_a_fake_ip_answer_is_recognised_as_fake(proxy_env):
    assert url_safety._is_fake_ip("198.18.0.31") is True
    assert url_safety._is_fake_ip("198.19.0.1") is True  # /15 spans 198.18-198.19
    assert url_safety._is_fake_ip("198.20.0.1") is False  # first address outside
    assert url_safety._is_fake_ip("10.0.0.5") is False
    assert url_safety._is_fake_ip("not-an-ip") is False


def test_proxy_detection_sees_each_variable(monkeypatch):
    for var in PROXY_VARS:
        for v in PROXY_VARS:
            monkeypatch.delenv(v, raising=False)
        monkeypatch.setenv(var, "http://127.0.0.1:7890")
        assert url_safety._proxy_in_effect() is True, f"{var} not detected"
