"""Contract tests for the content_quality / broken_link_checker move to extras.

Two things must both stay true, and they pull in opposite directions:

1. REFACTOR_PLAN.md says these are website-audit helpers that should leave
   Core, so the implementation lives in webscout_mcp.extras.
2. COMPATIBILITY.md freezes the 11 MCP tools including content_quality and
   broken_links, and existing code imports the old Python paths.

So the move is internal only: the tools keep working, the old import paths keep
working and emit a deprecation warning, and both paths resolve to the same
objects. These tests fail if someone breaks either half.
"""

from __future__ import annotations

import importlib
import warnings

import pytest


def _import_quiet(module: str):
    """Import a shim without letting its own DeprecationWarning fail the run."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        return importlib.import_module(module)


@pytest.fixture(autouse=True)
def _clear_modules():
    yield
    # Leave no half-imported shim behind for other tests.
    for name in (
        "webscout_mcp.content_quality",
        "webscout_mcp.broken_link_checker",
    ):
        import sys

        sys.modules.pop(name, None)


def test_content_quality_implementation_lives_in_extras():
    mod = _import_quiet("webscout_mcp.extras.content_quality")
    assert hasattr(mod, "ContentQualityAnalyzer")
    assert hasattr(mod, "ContentQualityMetrics")
    assert hasattr(mod, "analyze_content_quality")


def test_broken_link_checker_implementation_lives_in_extras():
    mod = _import_quiet("webscout_mcp.extras.broken_link_checker")
    assert hasattr(mod, "BrokenLinkChecker")
    assert hasattr(mod, "BrokenLinkReport")
    assert hasattr(mod, "LinkCheckResult")
    assert hasattr(mod, "check_broken_links")


def test_old_content_quality_path_still_imports():
    new = _import_quiet("webscout_mcp.extras.content_quality")
    old = _import_quiet("webscout_mcp.content_quality")
    assert old.ContentQualityMetrics is new.ContentQualityMetrics
    assert old.analyze_content_quality is new.analyze_content_quality


def test_old_broken_link_path_still_imports():
    new = _import_quiet("webscout_mcp.extras.broken_link_checker")
    old = _import_quiet("webscout_mcp.broken_link_checker")
    assert old.BrokenLinkChecker is new.BrokenLinkChecker
    assert old.check_broken_links is new.check_broken_links


def test_old_path_warns_about_the_move():
    """A silent move would strand callers; the warning is the migration signal."""
    import sys

    sys.modules.pop("webscout_mcp.content_quality", None)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        importlib.import_module("webscout_mcp.content_quality")
    messages = [str(w.message) for w in caught if issubclass(w.category, DeprecationWarning)]
    assert any("extras.content_quality" in m for m in messages), messages


def test_broken_link_shim_reexports_check_url_safe():
    """The shim keeps the name patchable at the old path.

    Tests and downstream code patch ``webscout_mcp.broken_link_checker
    .check_url_safe``. Dropping the name from the shim would raise AttributeError
    at patch time, not at import time, which is a confusing way to break.
    """
    old = _import_quiet("webscout_mcp.broken_link_checker")
    assert hasattr(old, "check_url_safe")


def test_old_and_new_share_one_module_instance():
    """Importing via either path must not create two separate implementations."""
    a = _import_quiet("webscout_mcp.extras.broken_link_checker")
    b = _import_quiet("webscout_mcp.broken_link_checker")
    assert a.BrokenLinkChecker.__module__ == b.BrokenLinkChecker.__module__
    assert a.BrokenLinkChecker.__module__ == "webscout_mcp.extras.broken_link_checker"


def test_mcp_tool_surface_is_unchanged():
    """The move must not remove or rename either MCP tool."""
    import asyncio
    import pathlib
    import tempfile

    from webscout_mcp.config import Config
    from webscout_mcp.server import create_server

    mcp = create_server(Config(cache_dir=pathlib.Path(tempfile.mkdtemp())))
    names = {t.name for t in asyncio.run(mcp.list_tools())}
    assert len(names) == 11, sorted(names)
    assert "content_quality" in names
    assert "broken_links" in names


def test_implementation_still_reaches_the_ssrf_guard():
    """Moving the module must not disconnect its security check.

    broken_link_checker enforces SSRF checks per redirect hop. If the move broke
    the ``..url_safety`` import the guard would silently vanish, and the earlier
    security fix in this file would be undone.
    """
    import inspect

    mod = _import_quiet("webscout_mcp.extras.broken_link_checker")
    src = inspect.getsource(mod)
    assert "check_url_safe" in src
    assert src.count("check_url_safe") >= 3, "expected per-hop guard call sites"
