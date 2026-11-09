"""Catch 3.11-only constructs locally, before the 3.10 CI job does.

The F4 checker imported `datetime.UTC`, which is 3.11+. Only the Python 3.10 CI
job failed; 3.11 and 3.12 passed, and this machine runs 3.12, so a local test run
said everything was fine.

Waiting for the oldest interpreter in the matrix is a slow way to learn this. The
project's support floor is 3.10 (REFACTOR_PLAN.md#L211), so the constructs that
break on 3.10 are enumerable and worth checking with the AST rather than text
matching - my first attempt flagged the words "datetime.UTC" inside a comment that
was explaining why not to use it.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = sorted((REPO / "scripts").glob("*.py"))
SCOPE = [REPO / "webscout_mcp"] + SCRIPTS

# Constructs added in 3.11 that would fail at import or call time on 3.10.
FORBIDDEN_ATTRS = {
    "datetime.UTC": "use timezone.utc (3.10 compatible)",
    "asyncio.TaskGroup": "use gather with explicit cancellation",
    "typing.Self": "use a quoted return type",
    "enum.StrEnum": "use str, Enum",
}
FORBIDDEN_IMPORTS = {"tomllib", "exceptiongroup"}


def _python_files():
    for target in SCOPE:
        if target.is_file():
            yield target
        else:
            for path in target.rglob("*.py"):
                if "__pycache__" not in str(path):
                    yield path


def _guarded_import_ids(tree: ast.AST) -> set[int]:
    """ids of import nodes sitting inside a Try that handles ImportError.

    `try: import tomllib / except ImportError: import tomli as tomllib` is the
    correct way to support 3.10, so those imports must not be reported. Without
    this the check flags its own fix and gets ignored.
    """
    guarded: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Try):
            continue
        handles_import_error = any(
            handler.type is None
            or (
                isinstance(handler.type, ast.Name)
                and handler.type.id in {"ImportError", "ModuleNotFoundError", "Exception"}
            )
            for handler in node.handlers
        )
        if not handles_import_error:
            continue
        for child in node.body:
            for inner in ast.walk(child):
                if isinstance(inner, (ast.Import, ast.ImportFrom)):
                    guarded.add(id(inner))
    return guarded


def _dotted(node: ast.AST) -> str | None:
    """Render Name.attr chains, ignoring anything that is not a plain chain."""
    parts: list[str] = []
    current = node
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if not isinstance(current, ast.Name):
        return None
    parts.append(current.id)
    return ".".join(reversed(parts))


@pytest.mark.parametrize("path", list(_python_files()), ids=lambda p: p.name)
def test_no_python_311_only_constructs(path):
    """Uses the AST so comments and strings mentioning a construct do not count."""
    tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    guarded = _guarded_import_ids(tree)

    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            dotted = _dotted(node)
            if dotted in FORBIDDEN_ATTRS:
                pytest.fail(f"{path.relative_to(REPO)}:{node.lineno} uses {dotted} (3.11+). {FORBIDDEN_ATTRS[dotted]}")

        if id(node) in guarded:
            continue

        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] in FORBIDDEN_IMPORTS:
                    pytest.fail(
                        f"{path.relative_to(REPO)}:{node.lineno} imports {alias.name} "
                        f"(3.11+) without an ImportError fallback"
                    )

        if isinstance(node, ast.ImportFrom) and node.module:
            root = node.module.split(".")[0]
            if root in FORBIDDEN_IMPORTS:
                pytest.fail(
                    f"{path.relative_to(REPO)}:{node.lineno} imports from {node.module} "
                    f"(3.11+) without an ImportError fallback"
                )


def test_the_promotion_checker_is_python310_compatible():
    """The specific regression, pinned where a 3.12-only local run can see it."""
    path = REPO / "scripts" / "check_promotion_evidence.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))

    froms = [n for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module == "datetime"]
    assert froms, "expected a datetime import"
    names = {alias.name for node in froms for alias in node.names}
    assert "UTC" not in names, "datetime.UTC does not exist on 3.10; use timezone.utc"
    assert "timezone" in names


def test_ast_check_ignores_mentions_in_comments():
    """The false positive that made the first version useless.

    A comment saying "not datetime.UTC" must not fail the scan.
    """
    source = "# do not use datetime.UTC here\nX = 1\n"
    tree = ast.parse(source)
    hits = [_dotted(n) for n in ast.walk(tree) if isinstance(n, ast.Attribute)]
    assert "datetime.UTC" not in hits
