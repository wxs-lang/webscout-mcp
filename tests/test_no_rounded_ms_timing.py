"""Guard: no rounded-millisecond timing may return to the package.

This defect has now been fixed five times — rag_optimizer, search_optimizer (x2),
broken_link_checker, ai_optimizer, ocr_engine, translator. Each time the symptom was
a duration of exactly 0.0 for a fast path, and each time the fix was local.

A static check is proportionate here because the bug is a *shape* in the source, not
a behaviour: `round((time.time() - start) * 1000, 2)` cannot express a duration below
10 microseconds, and any consumer asserting `> 0` breaks. Two decimals on a
millisecond scale simply cannot represent what these fields claim to measure.

The test asserts the whole package is free of the pattern. Adding it back anywhere
fails here, with the file and line named.
"""

from __future__ import annotations

import re
from pathlib import Path

PKG = Path(__file__).resolve().parent.parent / "webscout_mcp"

# round((time.time() - VAR) * 1000, 2)  — the exact idiom that collapses to 0.0
ROUNDED_MS = re.compile(r"round\(\s*\(\s*time\.time\(\)\s*-\s*\w+\s*\)\s*\*\s*1000\s*,\s*2\s*\)")


def _sources() -> list[tuple[Path, str]]:
    out = []
    for p in PKG.rglob("*.py"):
        if "__pycache__" in p.parts:
            continue
        out.append((p, p.read_text(encoding="utf-8", errors="replace")))
    return out


def test_no_rounded_millisecond_timing():
    offenders = []
    for path, src in _sources():
        for m in ROUNDED_MS.finditer(src):
            line = src[: m.start()].count("\n") + 1
            offenders.append(f"{path.relative_to(PKG)}:{line}")

    assert not offenders, (
        "millisecond durations are rounded to 2 decimals, which cannot represent a "
        "sub-10-microsecond span and returns exactly 0.0; use "
        "max(round((time.perf_counter() - start) * 1000, 4), 0.0001) instead "
        "— at: " + ", ".join(offenders)
    )


def test_the_checker_would_catch_the_pattern():
    """Guard the guard: the regex must match the real idiom, not only in theory."""
    sample = "x.latency_ms = round((time.time() - start_time) * 1000, 2)"
    assert ROUNDED_MS.search(sample), "the checker no longer recognises the pattern"

    # and must not fire on the corrected form
    fixed = "x.latency_ms = max(round((time.perf_counter() - start_time) * 1000, 4), 0.0001)"
    assert not ROUNDED_MS.search(fixed), "the checker rejects the corrected form"
