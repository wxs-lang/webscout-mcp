"""Guard the guard: prove the structural check catches the original defect.

A checker that passes everything looks exactly like a working one. This feeds the
checker the ORIGINAL bad pattern and the corrected good pattern, and asserts it
distinguishes them.

Without this, someone could relax the checker (or a refactor could make it match
nothing) and every test would stay green while the defect returned.
"""

from __future__ import annotations

import ast

ANTI_PATTERN = """
async def test_bing_failure_ddg_fallback_live(x):
    try:
        fallback_triggered = False
        assert fallback_triggered, "Fallback never triggered"
    except Exception as e:
        raise RuntimeError(f"crashed: {e}")
"""

CORRECT_PATTERN = """
async def test_bing_failure_ddg_fallback_live(x):
    unverified_reason = None
    try:
        unverified_reason = "Fallback never triggered"
    except Exception as e:
        raise RuntimeError(f"crashed: {e}")
    if unverified_reason:
        raise AssertionError(unverified_reason)
"""


def _asserts_inside_broad_try(src: str) -> list[int]:
    """The same rule the real test applies, over arbitrary source."""
    tree = ast.parse(src)
    fn = next(
        n
        for n in ast.walk(tree)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == "test_bing_failure_ddg_fallback_live"
    )
    found: list[int] = []
    for node in ast.walk(fn):
        if not isinstance(node, ast.Try):
            continue
        broad = any(
            h.type is None or (isinstance(h.type, ast.Name) and h.type.id in ("Exception", "BaseException"))
            for h in node.handlers
        )
        if not broad:
            continue
        for stmt in node.body:
            found.extend(inner.lineno for inner in ast.walk(stmt) if isinstance(inner, ast.Assert))
    return found


def test_the_checker_flags_the_original_defect():
    """If this fails, the structural test is vacuous."""
    assert _asserts_inside_broad_try(ANTI_PATTERN), (
        "the checker no longer detects an assert inside try/except Exception"
    )


def test_the_checker_accepts_the_corrected_pattern():
    """If this fails, the checker is over-strict and will block legitimate code."""
    assert _asserts_inside_broad_try(CORRECT_PATTERN) == []
