"""Regression guard for tool-count and web_fetch parameter drift.

These tests are deliberately static: they read the real server.py source so
that docs (README / COMPATIBILITY / MODULE_STATUS) cannot silently drift from
the actual MCP tool schema again (v1.3.0 RC fixed: README said 6 tools /
``max_length`` while the code had 11 tools / ``max_chars`` + ``start_char``).
"""

from __future__ import annotations

import re
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "webscout_mcp" / "server.py"
DOC = Path(__file__).resolve().parent.parent / "COMPATIBILITY.md"


def test_exactly_eleven_mcp_tools_registered():
    src = SRC.read_text(encoding="utf-8")
    assert src.count("@mcp.tool()") == 11, "MCP tool count must stay 11 (feature freeze)"


def test_web_fetch_signature_has_current_params():
    src = SRC.read_text(encoding="utf-8")
    start = src.index("async def web_fetch(")
    end = src.index("-> str:", start)
    block = src[start:end]
    for param in ("url", "extract", "output_format", "max_chars", "bypass_cache", "start_char"):
        assert re.search(rf"\b{param}\b", block), f"web_fetch missing parameter {param}"
    # The legacy parameter must never come back.
    assert "max_length" not in block, "web_fetch must use max_chars, not the legacy max_length"


def test_compatibility_doc_matches_real_schema():
    doc = DOC.read_text(encoding="utf-8")
    section = doc[doc.index("#### `web_fetch`") : doc.index("#### `web_crawl`")]
    assert "max_chars" in section, "COMPATIBILITY must document max_chars"
    assert "start_char" in section, "COMPATIBILITY must document the v1.3.0 start_char parameter"
    # The deprecated name must not appear as a live parameter.
    assert re.search(r"- `max_length`", section) is None, "COMPATIBILITY still lists legacy max_length"


def test_compatibility_version_header_not_stale():
    """The compatibility promise must not be frozen at v0.9/v1.0 while the
    project ships v1.3.x. We do not hard-code a release date (that would force
    every patch to touch this test); we only guard against the stale target."""
    doc = DOC.read_text(encoding="utf-8")
    assert "v0.9.0" not in doc, "COMPATIBILITY still references the stale v0.9.0 baseline"
    assert "Frozen for v1.0" not in doc, "COMPATIBILITY still says 'Frozen for v1.0'"
    assert "Target: **v1.0.0**" not in doc, "COMPATIBILITY still targets v1.0.0"
    # Header version line must track a v1.x (or later) release, not v0.x.
    m = re.search(r">\s*\*\*Version\*\*:\s*(v?\d+\.\d+\.\d+)", doc)
    assert m, "COMPATIBILITY header must carry a Version line"
    major = int(m.group(1).lstrip("v").split(".")[0])
    assert major >= 1, f"COMPATIBILITY header version {m.group(1)} is still a v0.x release"
