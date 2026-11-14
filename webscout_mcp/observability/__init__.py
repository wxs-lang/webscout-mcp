"""observability layer (step-7 reorganization)."""

# Re-export the telemetry core so the historical import path
# webscout_mcp.observability keeps working after observability.py
# joined the package as telemetry.py.
# Delegate any attribute missing from this package namespace to the
# telemetry module (including underscore-private names tests reference
# directly, e.g. _BACKEND_BUCKETS, _MAX_CONTENT_SAMPLES). Keeps the
# historical import path webscout_mcp.observability.<anything> alive after
# observability.py joined the package as telemetry.py — with zero list
# maintenance.
from . import telemetry as _telemetry
from .telemetry import *  # noqa: F401,F403

# Private names tests monkeypatch; import * skips underscore names.
from .telemetry import _BACKEND_BUCKETS  # noqa: F401


def __getattr__(name):  # module-level PEP 562
    return getattr(_telemetry, name)
