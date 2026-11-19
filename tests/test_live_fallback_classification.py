"""Pin the three outcomes of the live fallback test's error handling.

Why this needs its own test: the fix's entire value is the DISTINCTION. A version
that skipped on everything would look just as green as the correct one, and would
silently stop catching the regression the live test exists for. So each branch gets
an explicit assertion.

The classifier lives in tests/live/test_live_search.py, which imports live-test
dependencies. Import the module by path to avoid pulling the whole live suite into
the unit run.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

LIVE_TEST = Path(__file__).resolve().parent / "live" / "test_live_search.py"


def _load():
    """Import tests/live/test_live_search.py by path, under a stable name.

    Registering the module in sys.modules before executing it is required: the
    file defines dataclasses, and dataclasses looks its own module up there.
    """
    name = "live_search_probe"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, LIVE_TEST)
    if spec is None or spec.loader is None:
        pytest.skip(f"cannot load {LIVE_TEST}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    try:
        spec.loader.exec_module(mod)
    except Exception as exc:  # noqa: BLE001 - live deps may be absent
        pytest.skip(f"live test module not importable here: {type(exc).__name__}: {exc}")
    return mod


def test_connect_error_is_transport():
    mod = _load()
    import httpx

    assert mod._looks_like_transport_failure(httpx.ConnectError("boom")) is True


def test_timeout_is_transport():
    mod = _load()

    assert mod._looks_like_transport_failure(TimeoutError("timed out")) is True


def test_blocked_keyword_is_transport():
    mod = _load()

    class Blocked(Exception):
        pass

    assert mod._looks_like_transport_failure(Blocked("request blocked by provider")) is True


def test_assertion_error_is_never_transport():
    """The regression the test exists for must still fail."""
    mod = _load()

    assert mod._looks_like_transport_failure(AssertionError("fallback never triggered")) is False


def test_ordinary_error_is_not_transport():
    """A real bug in the code path must not be excused as a network problem."""
    mod = _load()

    assert mod._looks_like_transport_failure(ValueError("bad parameter")) is False
