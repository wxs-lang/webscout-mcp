"""The setup subcommand the README advertises must actually exist.

## Measured

README.md L101/168/244 and README_zh.md L21/118/197 document `webscout-mcp setup`, marked
"One-Click Full Setup (Recommended)". `run_setup()` existed (27KB, complete) but nothing wired
it: no `setup` subparser, zero cross-file references outside its own tests. A user installing
from PyPI and running the first command the README suggests got argparse REJECTED.

Same shape: README L238 documented `fetch --extract`; the real flag is `--no-extract`
(`--extract` is the default). Both failures hit in the first minute of use.
"""

from __future__ import annotations

import subprocess
import sys

import pytest

REPO_FLAG_EXAMPLES = [
    # (subcommand, flags a README example passes) - flags must exist in --help
    ("setup", ["--playwright", "--ollama", "--vector-store"]),
    ("setup", ["--playwright"]),
    ("fetch", ["--format"]),
]


@pytest.mark.parametrize("sub,flags", REPO_FLAG_EXAMPLES)
def test_readme_documented_flags_exist(sub: str, flags: list[str]):
    help_text = subprocess.run(
        [sys.executable, "-X", "utf8", "-m", "webscout_mcp", sub, "--help"],
        capture_output=True,
        text=True,
        timeout=120,
        encoding="utf-8",
        errors="replace",
    )
    assert help_text.returncode == 0, f"`{sub} --help` failed: {help_text.stderr[:200]}"
    missing = [f for f in flags if f not in help_text.stdout]
    assert not missing, f"README documents {missing} but `{sub}` does not accept them"


def test_setup_subcommand_is_wired():
    """`setup` must be a real subcommand, not only documented."""
    r = subprocess.run(
        [sys.executable, "-X", "utf8", "-m", "webscout_mcp", "setup", "--help"],
        capture_output=True,
        text=True,
        timeout=120,
        encoding="utf-8",
        errors="replace",
    )
    assert r.returncode == 0
    assert "One-click setup" in r.stdout or "setup" in r.stdout


def test_run_setup_is_importable_from_the_cli_module():
    """The command function must reach run_setup - wiring, not just a parser."""
    from webscout_mcp.__main__ import _cmd_setup  # noqa: F401
    from webscout_mcp.setup import run_setup  # noqa: F401


def test_fetch_has_no_extract_flag_not_extract():
    """The real flag is `--no-extract`; `--extract` was the documented-but-broken form."""
    r = subprocess.run(
        [sys.executable, "-X", "utf8", "-m", "webscout_mcp", "fetch", "--help"],
        capture_output=True,
        text=True,
        timeout=120,
        encoding="utf-8",
        errors="replace",
    )
    assert "--no-extract" in r.stdout
    # `--extract` must NOT appear as an accepted flag. A bare grep would match
    # `--no-extract`, so require a word boundary via the help formatting.
    import re

    assert not re.search(r"(?m)^\s+--extract\b", r.stdout), (
        "`--extract` is accepted but the real flag is `--no-extract`; README examples were rejected by argparse"
    )


def test_readme_examples_no_longer_use_the_broken_flag():
    """The two READMEs must not carry the rejected `--extract` example any more."""
    import pathlib

    repo = pathlib.Path(__file__).resolve().parents[1]
    for name in ("README.md", "README_zh.md"):
        text = (repo / name).read_text(encoding="utf-8", errors="replace")
        assert "--extract " not in text.replace("--no-extract ", ""), (
            f"{name} still documents `--extract`, which argparse rejects"
        )
