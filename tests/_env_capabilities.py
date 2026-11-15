"""Environment-capability detection for tests.

Some tests fail for reasons that are environment facts, not code defects.
Detecting the fact explicitly turns a red suite into a signal: "N known
environment skips, M real failures" instead of an undifferentiated wall.

1. **Intercepted DNS.** A transparent proxy (iKuuuVPN, Clash, sing-box) can
   resolve public hostnames into 198.18.0.0/15. The SSRF guard correctly
   refuses those as non-public, so tests that push a public URL through the
   real safety check fail with a message that reads like a bug but is the
   guard working as designed.

   Measured on this machine: with the proxy up
   `example.com -> 198.18.0.34`; with it down `example.com -> 172.66.147.243`.
   A suite that flips with the proxy state is worse than one that skips
   loudly, and worse again if it flips between runs of the same commit.

   The probe uses `socket.getaddrinfo`, the same call the product's SSRF
   guard makes. Probing with `gethostbyname` was tried first and returned a
   stale answer (False while the guard was rejecting), so "detected" and
   "the guard will reject this" would have disagreed.

2. **POSIX file modes.** Windows has no 0600; `stat().st_mode & 0o777` returns
   0o666 for a file the code did restrict. Permission-bit assertions are
   POSIX-only by nature.

Detection is evaluated at *fixture setup*, i.e. at test execution, not at
module import: the DNS answer can differ between the two.

Usage — request the fixture by name; it skips the test when the capability is
missing:

    def test_fetch_public_page(requires_public_dns):
        ...

    def test_key_file_is_0600(requires_posix_modes):
        ...
"""

from __future__ import annotations

import os
import sys

import pytest
from _dns_probe import dns_is_intercepted


def posix_modes_available() -> bool:
    """True where chmod 0600 is enforceable (not Windows)."""
    return os.name == "posix" and sys.platform != "win32"


@pytest.fixture
def requires_public_dns() -> None:
    """Skip when DNS answers are intercepted; SSRF checks would reject them."""
    if dns_is_intercepted():
        pytest.skip(
            "DNS is intercepted by a transparent proxy (public hosts resolve "
            "into 198.18.0.0/15); the SSRF guard correctly rejects those, so "
            "this test cannot exercise its intended path here"
        )


@pytest.fixture
def requires_posix_modes() -> None:
    """Skip on platforms without POSIX permission-bit semantics."""
    if not posix_modes_available():
        pytest.skip("POSIX file-mode semantics (0600) do not exist on this platform")
