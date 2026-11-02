"""TLS impersonation: the CA-path hazard, profile rotation, and the fallback.

Two behaviours are easy to get wrong and were both hit while building this:

1. libcurl cannot open a CA bundle under a non-ASCII path (curl error 77). On this
   machine `D:\\测试\\...` triggered it and the failure looked like a network
   problem. The staging logic must be tested without needing a non-ASCII install,
   so the helper is exercised directly.

2. Profile choice is target-dependent - reddit returns 166KB to chrome131 and 8KB
   to safari, reuters the reverse - so the loop must actually try more than one.

Nothing here touches the network: the fetcher integration is tested with the
impersonation call monkeypatched, so the suite stays offline and deterministic.
"""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

import pytest

from webscout_mcp import tls_impersonation as ti


@pytest.fixture(autouse=True)
def _reset_module_cache():
    """The module caches availability and the CA path; tests need a clean slate."""
    ti._ca_bundle = None
    ti._available = None
    yield
    ti._ca_bundle = None
    ti._available = None


# --- CA bundle handling ------------------------------------------------


def test_ascii_check_accepts_a_plain_path():
    assert ti._is_ascii(r"C:\Users\x\cacert.pem")


def test_ascii_check_rejects_a_cjk_path():
    assert not ti._is_ascii("D:\\测试\\_tls\\cacert.pem")


def test_staging_is_skipped_when_the_source_is_already_ascii(monkeypatch, tmp_path):
    """Copying would be pointless work on every normal install."""
    ascii_ca = tmp_path / "cacert.pem"
    ascii_ca.write_text("dummy", encoding="utf-8")

    import certifi

    monkeypatch.setattr(certifi, "where", lambda: str(ascii_ca))

    result = ti._ascii_ca_bundle()
    assert result == str(ascii_ca)
    assert ti._is_ascii(result)


def test_staging_copies_a_non_ascii_bundle_to_an_ascii_location(monkeypatch, tmp_path):
    """This is the fix for curl error 77."""
    source_dir = tmp_path / "测试目录"
    source_dir.mkdir()
    source = source_dir / "cacert.pem"
    source.write_text("dummy-ca", encoding="utf-8")

    import certifi

    monkeypatch.setattr(certifi, "where", lambda: str(source))
    monkeypatch.setattr(ti.tempfile, "gettempdir", lambda: str(tmp_path / "ascii"))

    result = ti._ascii_ca_bundle()
    assert result is not None
    assert ti._is_ascii(result)
    assert Path(result).read_text(encoding="utf-8") == "dummy-ca"


def test_unavailable_when_curl_cffi_is_missing(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "curl_cffi":
            raise ImportError("simulated")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    assert ti.is_available() is False


# --- Profile rotation --------------------------------------------------


def test_fetch_impersonated_tries_every_profile(monkeypatch):
    """One profile is not enough: which one works depends on the target."""
    tried: list[str] = []

    class _Resp:
        def __init__(self, status, text):
            self.status_code = status
            self.text = text

    class _FakeRequests:
        @staticmethod
        def get(url, impersonate=None, **_kwargs):
            tried.append(impersonate)
            if impersonate == "safari17_0":
                return _Resp(403, "blocked")
            return _Resp(200, "the article")

    import sys
    import types

    fake_module = types.SimpleNamespace(requests=_FakeRequests)
    monkeypatch.setitem(sys.modules, "curl_cffi", fake_module)
    monkeypatch.setattr(ti, "is_available", lambda: True)
    monkeypatch.setattr(ti, "_ascii_ca_bundle", lambda: "/tmp/ca.pem")

    status, body, profile = ti.fetch_impersonated("https://example.test/", profiles=("safari17_0", "chrome131"))
    assert status == 200
    assert body == "the article"
    assert profile == "chrome131"
    assert tried == ["safari17_0", "chrome131"], "must fall through to the next profile"


def test_fetch_impersonated_gives_up_cleanly_when_all_profiles_fail(monkeypatch):
    class _Resp:
        status_code = 403
        text = "blocked"

    class _FakeRequests:
        @staticmethod
        def get(url, impersonate=None, **_kwargs):  # noqa: ARG004
            return _Resp()

    import sys
    import types

    monkeypatch.setitem(sys.modules, "curl_cffi", types.SimpleNamespace(requests=_FakeRequests))
    monkeypatch.setattr(ti, "is_available", lambda: True)
    monkeypatch.setattr(ti, "_ascii_ca_bundle", lambda: "/tmp/ca.pem")

    status, body, profile = ti.fetch_impersonated("https://example.test/", profiles=("chrome131",))
    # The body of the failed attempt is kept so a caller can tell an anti-bot challenge
    # from a transport problem: a DataDome 401 carries "Please enable JS" plus an
    # `x-datome: protected` header, and discarding it left the caller unable to diagnose.
    # The empty profile is what still distinguishes failure from success.
    assert body == "blocked"
    assert profile == ""
    assert status == 403


def test_fetch_impersonated_keeps_the_challenge_page_for_diagnosis(monkeypatch):
    """A 401 from an anti-bot wall must arrive with its body, not as an empty string.

    Measured on reuters: `x-datadome: protected` and a `captcha-delivery.com` script in
    the body. Returning "" made "challenged" indistinguishable from "could not connect".
    """
    challenge = '<html><body><p id="cmsg">Please enable JS</p></body></html>'

    class _Resp:
        status_code = 401
        text = challenge

    class _FakeRequests:
        @staticmethod
        def get(url, impersonate=None, **_kwargs):  # noqa: ARG004
            return _Resp()

    import sys
    import types

    monkeypatch.setitem(sys.modules, "curl_cffi", types.SimpleNamespace(requests=_FakeRequests))
    monkeypatch.setattr(ti, "is_available", lambda: True)
    monkeypatch.setattr(ti, "_ascii_ca_bundle", lambda: "/tmp/ca.pem")

    status, body, profile = ti.fetch_impersonated("https://example.test/", profiles=("safari17_0",))
    assert status == 401
    assert body == challenge, "the challenge page is the diagnosis"
    assert profile == "", "an empty profile still marks this as a failure"


def test_fetch_impersonated_returns_empty_when_unavailable(monkeypatch):
    monkeypatch.setattr(ti, "is_available", lambda: False)
    assert ti.fetch_impersonated("https://example.test/") == (0, "", "")


def test_transport_exception_moves_to_the_next_profile(monkeypatch):
    class _FakeRequests:
        calls = 0

        @classmethod
        def get(cls, url, impersonate=None, **_kwargs):  # noqa: ARG003
            cls.calls += 1
            if cls.calls == 1:
                raise OSError("connection reset")
            return type("R", (), {"status_code": 200, "text": "ok"})()

    import sys
    import types

    monkeypatch.setitem(sys.modules, "curl_cffi", types.SimpleNamespace(requests=_FakeRequests))
    monkeypatch.setattr(ti, "is_available", lambda: True)
    monkeypatch.setattr(ti, "_ascii_ca_bundle", lambda: "/tmp/ca.pem")

    status, body, _ = ti.fetch_impersonated("https://example.test/", profiles=("a", "b"))
    assert (status, body) == (200, "ok")


def test_describe_reports_profiles_and_availability(monkeypatch):
    monkeypatch.setattr(ti, "is_available", lambda: True)
    info = ti.describe()
    assert info["available"] is True
    assert "safari17_0" in info["profiles"]


# --- Fetcher integration (offline) ------------------------------------


def test_403_triggers_impersonation_and_returns_content(monkeypatch, tmp_path):
    """The whole point: a 403 that is really a handshake rejection gets retried."""
    from webscout_mcp.core.cache import Cache
    from webscout_mcp.core.config import Config
    from webscout_mcp.fetcher import Fetcher

    cfg = Config.from_env()
    fetcher = Fetcher(cfg, Cache(db_path=tmp_path / "c.db", ttl=60, max_size_mb=4))

    class _Resp403:
        status_code = 403
        headers = {"content-type": "text/html"}
        url = "https://blocked.test/"
        text = "<html><body>blocked</body></html>"
        reason_phrase = "Forbidden"
        encoding = "utf-8"

    class _Client:
        async def get(self, url, follow_redirects=True):  # noqa: ARG002
            return _Resp403()

    async def _fake_client():
        return _Client()

    monkeypatch.setattr(fetcher, "_get_client", _fake_client)
    monkeypatch.setattr(
        "webscout_mcp.tls_impersonation.fetch_impersonated",
        lambda url, timeout=30.0, profiles=None: (200, "<html><body>real article</body></html>", "chrome131"),
    )

    result = asyncio.run(fetcher.fetch("https://blocked.test/", extract=False, bypass_cache=True))
    assert result.status_code == 200
    assert "real article" in result.content
    assert result.metadata.get("tls_impersonation") == "chrome131"
    assert result.metadata.get("original_status") == 403


def test_403_without_impersonation_keeps_the_original_response(monkeypatch, tmp_path):
    """When impersonation cannot help, behaviour must be exactly as before."""
    from webscout_mcp.core.cache import Cache
    from webscout_mcp.core.config import Config
    from webscout_mcp.fetcher import Fetcher

    cfg = Config.from_env()
    fetcher = Fetcher(cfg, Cache(db_path=tmp_path / "c.db", ttl=60, max_size_mb=4))

    class _Resp403:
        status_code = 403
        headers = {"content-type": "text/html"}
        url = "https://blocked.test/"
        text = "<html><body>blocked</body></html>"
        reason_phrase = "Forbidden"
        encoding = "utf-8"

    class _Client:
        async def get(self, url, follow_redirects=True):  # noqa: ARG002
            return _Resp403()

    async def _fake_client():
        return _Client()

    monkeypatch.setattr(fetcher, "_get_client", _fake_client)
    monkeypatch.setattr(
        "webscout_mcp.tls_impersonation.fetch_impersonated",
        lambda url, timeout=30.0, profiles=None: (403, "", ""),
    )

    result = asyncio.run(fetcher.fetch("https://blocked.test/", extract=False, bypass_cache=True))
    assert result.status_code == 403
    assert "Forbidden" in (result.error or "")
    assert "tls_impersonation" not in (result.metadata or {})


def test_successful_request_never_uses_impersonation(monkeypatch, tmp_path):
    """It must stay a fallback, not a default - it was never needed here."""
    from webscout_mcp.core.cache import Cache
    from webscout_mcp.core.config import Config
    from webscout_mcp.fetcher import Fetcher

    cfg = Config.from_env()
    fetcher = Fetcher(cfg, Cache(db_path=tmp_path / "c.db", ttl=60, max_size_mb=4))

    class _Resp200:
        status_code = 200
        headers = {"content-type": "text/html"}
        url = "https://ok.test/"
        text = "<html><body>fine</body></html>"
        reason_phrase = "OK"
        encoding = "utf-8"

    class _Client:
        async def get(self, url, follow_redirects=True):  # noqa: ARG002
            return _Resp200()

    async def _fake_client():
        return _Client()

    called = {"n": 0}

    def _spy(*_args, **_kwargs):
        called["n"] += 1
        return (200, "should not be used", "chrome131")

    monkeypatch.setattr(fetcher, "_get_client", _fake_client)
    monkeypatch.setattr("webscout_mcp.tls_impersonation.fetch_impersonated", _spy)

    result = asyncio.run(fetcher.fetch("https://ok.test/", extract=False, bypass_cache=True))
    assert result.status_code == 200
    assert called["n"] == 0, "a 200 must not pay for impersonation"


def test_caller_rejects_a_challenge_page_as_content():
    """The fetcher must not hand a "Please enable JS" page back as an article.

    `fetch_impersonated` returns the failure body for diagnosis, so the call site has to
    check the status: `if imp_status and imp_body` would accept a 401 challenge page as
    content, which is what the body-preserving change made possible.
    """
    import pathlib

    source = pathlib.Path("webscout_mcp/fetcher.py").read_text(encoding="utf-8")
    assert "if imp_status and imp_body:" not in source, (
        "a bare truthiness check accepts a 401 challenge page as content"
    )
    assert "if 200 <= imp_status < 300 and imp_body:" in source, "the caller must require a 2xx status"
