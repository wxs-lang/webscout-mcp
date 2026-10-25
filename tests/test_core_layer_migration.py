"""The first step of the five-layer reorganisation: errors moves to core/.

REFACTOR_PLAN.md describes a five-layer structure (server / services / providers
/ core / security / observability). The error taxonomy is the cleanest first
move because it has zero internal dependencies while being imported by ten
modules - a genuine infrastructure layer.

Two things must hold for this to be a reorganisation rather than a break:

1. the implementation lives in webscout_mcp.core.errors
2. webscout_mcp.errors keeps working, resolving to the same objects

Anything less means either the layering is cosmetic or existing callers broke.
"""

from __future__ import annotations

import importlib
import sys
import warnings
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]


def _quiet(module: str):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        return importlib.import_module(module)


@pytest.fixture(autouse=True)
def _clear_shim():
    yield
    sys.modules.pop("webscout_mcp.errors", None)


# --- Implementation location ------------------------------------------


def test_errors_implementation_lives_in_core():
    mod = _quiet("webscout_mcp.core.errors")
    assert hasattr(mod, "StandardErrorCode")
    assert hasattr(mod, "WebScoutError")
    assert hasattr(mod, "StructuredError")
    assert mod.__name__ == "webscout_mcp.core.errors"


def test_core_package_exists_and_is_documented():
    core = _quiet("webscout_mcp.core")
    assert core.__doc__, "the layer should say what it is for"
    assert "infrastructure" in core.__doc__.lower()


def test_the_moved_module_has_no_dependencies_on_higher_layers():
    """A core module that imports from its callers is not a core module.

    This is the property that makes the layering real, so it is worth asserting
    rather than assuming: a future edit that reaches upward would silently
    invert the dependency direction.
    """
    src = (REPO / "webscout_mcp" / "core" / "errors.py").read_text(encoding="utf-8")
    for line in src.splitlines():
        stripped = line.strip()
        if not stripped.startswith(("from .", "import webscout_mcp")):
            continue
        # Only relative imports within core/ are acceptable.
        assert stripped.startswith("from ."), f"core/errors.py reaches outside core: {stripped}"
        target = stripped.split()[1]
        assert not target.startswith(".."), f"core/errors.py imports from a parent package: {stripped}"


# --- Compatibility ----------------------------------------------------


def test_old_path_still_resolves_to_the_same_objects():
    new = _quiet("webscout_mcp.core.errors")
    old = _quiet("webscout_mcp.errors")
    assert old.StandardErrorCode is new.StandardErrorCode
    assert old.WebScoutError is new.WebScoutError
    assert old.StructuredError is new.StructuredError


def test_old_path_warns():
    """A silent move would strand callers; the warning is the migration signal."""
    sys.modules.pop("webscout_mcp.errors", None)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        importlib.import_module("webscout_mcp.errors")
    messages = [str(w.message) for w in caught if issubclass(w.category, DeprecationWarning)]
    assert any("core.errors" in m for m in messages), messages


def test_old_path_reexports_more_than_a_handful_of_names():
    """The module defines 50+ exception types; the shim must not truncate them.

    Star import was chosen over an explicit list precisely so a newly added
    exception cannot be silently omitted from the compatibility surface.
    """
    old = _quiet("webscout_mcp.errors")
    exported = [n for n in dir(old) if not n.startswith("_")]
    assert len(exported) > 40, f"only {len(exported)} names reachable through the shim"


def test_representative_exceptions_survive_the_shim():
    old = _quiet("webscout_mcp.errors")
    for name in (
        "WebScoutError",
        "FetchError",
        "SearchError",
        "SecurityError",
        "SSRFError",
        "CacheError",
        "PluginError",
        "ValidationError",
    ):
        assert hasattr(old, name), f"{name} lost in the move"


# --- Internal callers were updated ------------------------------------


def test_most_internal_modules_now_import_from_core():
    """The shim is for external callers, not an excuse to keep the flat path.

    If internal code kept importing webscout_mcp.errors it would trigger a
    deprecation warning on every package import.
    """
    offenders = []
    for path in (REPO / "webscout_mcp").rglob("*.py"):
        if "__pycache__" in str(path) or path.name == "errors.py":
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if "from .errors import" in text:
            offenders.append(path.name)
    assert offenders == [], f"still importing the shim internally: {offenders}"


def test_importing_the_package_emits_no_deprecation_for_errors():
    code = "import warnings, sys\nwarnings.simplefilter('error', DeprecationWarning)\nimport webscout_mcp.server\n"
    import subprocess

    proc = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        cwd=REPO,
        env={**__import__("os").environ, "PYTHONPATH": str(REPO)},
    )
    # A DeprecationWarning about errors would surface here as a failure.
    assert "errors is deprecated" not in (proc.stderr or ""), proc.stderr


# --- Behaviour is unchanged -------------------------------------------


def test_error_codes_are_unchanged():
    mod = _quiet("webscout_mcp.core.errors")
    codes = {c.name for c in mod.StandardErrorCode}
    assert "FETCH_TIMEOUT" in codes
    assert "FETCH_FORBIDDEN" in codes
    assert "SEARCH_RATE_LIMITED" in codes
    assert len(codes) >= 10


def test_a_structured_error_still_serialises():
    mod = _quiet("webscout_mcp.core.errors")
    err = mod.StructuredError(
        code=mod.StandardErrorCode.FETCH_TIMEOUT,
        message="timed out",
    )
    data = err.to_dict()
    assert data["code"] == "FETCH_TIMEOUT"
    assert data["message"] == "timed out"
