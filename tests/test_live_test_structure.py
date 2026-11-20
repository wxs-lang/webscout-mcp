"""Guard the structural defect, not just its symptom.

The bug: an `assert` inside a `try/except Exception` block has its AssertionError
swallowed, relabelled "crashed", and re-raised with a generic message. The real
diagnosis ("fallback never triggered, total=0") was invisible in CI, which is why
two rounds of investigation went looking for a network problem.

A test that asserts on function behaviour cannot catch this — the behaviour was
already wrong-but-plausible. What can catch it is reading the source: no `assert`
statement may live inside the try block of that test.

That is a static check on test code, which is unusual but proportionate: the defect
is about control flow, and it cost two rounds to see.
"""

from __future__ import annotations

import ast
from pathlib import Path

LIVE = Path(__file__).resolve().parent / "live" / "test_live_search.py"
TARGET = "test_bing_failure_ddg_fallback_live"


def _find_test(tree: ast.Module) -> ast.AsyncFunctionDef | ast.FunctionDef | None:
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == TARGET:
            return node
    return None


def test_no_assert_statement_inside_the_try_block():
    """An assert inside try/except Exception gets relabelled as a crash."""
    tree = ast.parse(LIVE.read_text(encoding="utf-8"))
    fn = _find_test(tree)
    assert fn is not None, f"{TARGET} not found"

    offenders: list[int] = []
    for node in ast.walk(fn):
        if not isinstance(node, ast.Try):
            continue
        # does this try have a broad handler?
        broad = any(
            h.type is None or (isinstance(h.type, ast.Name) and h.type.id in ("Exception", "BaseException"))
            for h in node.handlers
        )
        if not broad:
            continue
        for stmt in node.body:
            for inner in ast.walk(stmt):
                if isinstance(inner, ast.Assert):
                    offenders.append(inner.lineno)

    assert not offenders, (
        f"assert statements at lines {offenders} sit inside a try/except Exception "
        f"block; their AssertionError will be caught and reported as a crash, "
        f"burying the diagnosis"
    )


def test_the_outcome_is_asserted_after_the_handler():
    """The check that matters must still exist, just outside the try block."""
    tree = ast.parse(LIVE.read_text(encoding="utf-8"))
    fn = _find_test(tree)
    assert fn is not None

    # a fail() call referencing the recorded reason must exist at function level
    top_level_fails = [
        n
        for stmt in fn.body
        for n in ast.walk(stmt)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "fail"
    ]
    assert top_level_fails, "the unverified outcome must be reported at function level, outside the handler"


def test_the_reason_variable_is_initialised_before_the_try():
    """Otherwise the post-handler assertion would raise UnboundLocalError."""
    tree = ast.parse(LIVE.read_text(encoding="utf-8"))
    fn = _find_test(tree)
    assert fn is not None

    names_before_try = set()
    for stmt in fn.body:
        if isinstance(stmt, ast.Try):
            break
        for n in ast.walk(stmt):
            if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store):
                names_before_try.add(n.id)

    assert "unverified_reason" in names_before_try, "unverified_reason must be initialised before the try block"
