"""GOAL.md E2 must have actual evidence behind it.

The criterion reads "`pip install webscout-mcp` 后 CLI 可启动", verified by an
"安装冒烟" test. An audit of the repo found that evidence did not exist:

  - no test file covered it
  - verify_installation.py checked 13 things but never the entry point
  - CI never ran verify_installation.py
  - CI never ran `pip install .`

So a broken entry point, or a package missing from the wheel, would have reached
PyPI before anyone noticed. These tests keep the evidence from disappearing
again.

They are structural plus one live check: the structural half fails if someone
removes the wiring, the live half fails if the CLI stops working on this
platform.
"""

from __future__ import annotations

import ast
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
VERIFY = REPO / "scripts" / "verify_installation.py"
TESTS_YML = REPO / ".github" / "workflows" / "tests.yml"
PYPROJECT = REPO / "pyproject.toml"


# --- The entry point is declared ---------------------------------------


def test_pyproject_declares_the_console_script():
    """Without this, `pip install` produces a package with no command."""
    text = PYPROJECT.read_text(encoding="utf-8")
    assert "[project.scripts]" in text
    assert 'webscout-mcp = "webscout_mcp.__main__:main"' in text


def test_main_module_exposes_main():
    """The entry point target must be importable and callable."""
    import webscout_mcp.__main__ as entry

    assert callable(getattr(entry, "main", None))


# --- verify_installation covers the CLI --------------------------------


def test_verify_installation_defines_the_cli_check():
    src = VERIFY.read_text(encoding="utf-8")
    tree = ast.parse(src)
    names = {n.name for n in tree.body if isinstance(n, ast.FunctionDef)}
    assert "check_cli_entry_point" in names
    assert "_package_installed" in names


def test_verify_installation_registers_the_check():
    """A defined-but-uncalled check is the exact bug this fixes."""
    src = VERIFY.read_text(encoding="utf-8")
    assert 'checks.append(("CLI entry point", check_cli_entry_point))' in src


def test_cli_check_is_skipped_when_not_installed():
    """A source checkout has no console script; that is not a failure."""
    src = VERIFY.read_text(encoding="utf-8")
    assert "if _package_installed():" in src


def test_verify_installation_survives_a_non_utf8_console():
    """It prints status glyphs and used to crash on cp936.

    A script whose purpose is verifying cross-platform installation failed on
    the platform it was run from - unnoticed because CI never invoked it.
    """
    src = VERIFY.read_text(encoding="utf-8")
    assert "sys.stdout.reconfigure" in src, "no encoding guard: this crashes on cp936"


# --- CI runs an install smoke -----------------------------------------


def test_ci_has_an_install_smoke_job():
    text = TESTS_YML.read_text(encoding="utf-8")
    assert "install-smoke:" in text


def test_ci_builds_a_wheel_not_an_editable_install():
    """`pip install -e .` proves nothing about what users receive."""
    text = TESTS_YML.read_text(encoding="utf-8")
    job = text.split("install-smoke:", 1)[1]
    assert "python -m build --wheel" in job
    assert "dist/*.whl" in job


def test_ci_runs_the_installed_command():
    text = TESTS_YML.read_text(encoding="utf-8")
    job = text.split("install-smoke:", 1)[1]
    assert "webscout-mcp --version" in job
    assert "webscout-mcp --help" in job


def test_ci_uses_a_clean_virtualenv():
    """Installing into the runner's environment would hide missing deps."""
    text = TESTS_YML.read_text(encoding="utf-8")
    job = text.split("install-smoke:", 1)[1]
    assert "python -m venv" in job


def test_ci_checks_version_against_the_git_tag():
    """Guards the stale _version.py failure mode.

    An installed package reporting an old version is a packaging bug nothing
    else catches.
    """
    text = TESTS_YML.read_text(encoding="utf-8")
    job = text.split("install-smoke:", 1)[1]
    assert "git describe --tags" in job


def test_ci_runs_verify_installation_against_the_wheel():
    text = TESTS_YML.read_text(encoding="utf-8")
    job = text.split("install-smoke:", 1)[1]
    assert "verify_installation.py" in job


# --- Live check on this machine ---------------------------------------


def test_cli_responds_if_it_is_installed():
    """Where the console script exists, it must work.

    Skipped rather than failed when running from a bare source checkout, which
    is the same rule verify_installation uses.
    """
    exe = shutil.which("webscout-mcp")
    if not exe:
        return  # not installed here; the CI job covers that case

    proc = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr
    assert "webscout-mcp" in proc.stdout


def test_module_entry_point_runs_from_source():
    """`python -m webscout_mcp` works even without an install."""
    proc = subprocess.run(
        [sys.executable, "-m", "webscout_mcp", "--version"],
        capture_output=True,
        text=True,
        timeout=120,
        cwd=REPO,
        env={**__import__("os").environ, "PYTHONPATH": str(REPO)},
    )
    assert proc.returncode == 0, proc.stderr
    assert "webscout-mcp" in proc.stdout
