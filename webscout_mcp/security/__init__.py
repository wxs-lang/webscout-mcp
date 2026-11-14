"""security layer: introduced by the step-7 reorganization."""

# Re-export the SSRF protector and the other symbols the old top-level
# security.py carried, so the historical import paths
# (webscout_mcp.security / webscout_mcp.security.SSRFProtector) keep working
# after security.py joined the package as protector.py.
# Delegate missing attributes to the implementation submodule (PEP 562).
from . import protector as _impl
from .protector import *  # noqa: F401,F403


def __getattr__(name):  # module-level PEP 562
    return getattr(_impl, name)
