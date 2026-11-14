"""server layer (step-7 reorganization)."""

# Re-export the MCP server factory so the historical import path
# webscout_mcp.server keeps working after server.py joined the package
# as mcp_server.py.
# Delegate missing attributes to the implementation submodule (PEP 562):
# covers underscore-private names tests reference directly, with zero list
# maintenance. See observability/__init__.py for the pattern rationale.
from . import mcp_server as _impl
from . import mcp_server as mcp_server  # noqa: F401 — legacy attr path
from .mcp_server import *  # noqa: F401,F403

# Private helper some tests patch directly; import * skips it.
from .mcp_server import _empty_fetch_reason  # noqa: F401


def __getattr__(name):  # module-level PEP 562
    return getattr(_impl, name)
