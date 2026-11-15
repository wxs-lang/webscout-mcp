"""The seven-layer architecture must stay true, not just be true today.

This test wraps scripts/check_layers.py so a future commit that reaches
upward (or leaks a side branch into a lower layer) fails the suite instead
of quietly eroding the structure.

History: two upward edges survived the whole reorganization because the
move-time guard only inspected modules being moved. An end-state check
caught them. This test is that check, permanently.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def test_layer_discipline_holds():
    """No lower layer may import a higher one; no side branch may leak down."""
    r = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "check_layers.py"), "--quiet"],
        cwd=REPO,
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, "layer discipline violated:\n" + (r.stdout or "") + (r.stderr or "")


def test_the_checker_detects_a_violation(tmp_path):
    """Guard the guard: a synthetic upward import must be reported.

    Without this, a broken checker that always exits 0 would make the test
    above meaningless.
    """
    pkg = tmp_path / "fake_pkg"
    (pkg / "core").mkdir(parents=True)
    (pkg / "providers").mkdir(parents=True)
    (pkg / "core" / "__init__.py").write_text("")
    (pkg / "providers" / "__init__.py").write_text("")
    # core (depth 0) importing providers (depth 4) — the violation shape
    (pkg / "core" / "bad.py").write_text("from ..providers.thing import Widget\n")
    (pkg / "providers" / "thing.py").write_text("class Widget: pass\n")

    r = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "check_layers.py"), "--package", str(pkg), "--quiet"],
        cwd=REPO,
        capture_output=True,
        text=True,
    )
    assert r.returncode == 1, f"checker missed a real violation: {r.stdout}{r.stderr}"
    assert "core/bad" in r.stdout and "providers/thing" in r.stdout
