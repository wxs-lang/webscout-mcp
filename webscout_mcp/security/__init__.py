"""security layer: introduced by the step-7 reorganization."""

# Re-export the SSRF protector and other security.py symbols so the
# historical import path (webscout_mcp.security.SSRFProtector) keeps working
# after security.py joined the package as protector.py.

from .protector import *  # noqa: F401,F403
