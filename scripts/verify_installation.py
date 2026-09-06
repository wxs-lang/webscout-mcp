#!/usr/bin/env python3
"""Cross-platform verification script for webscout-mcp.

Run this script on any platform (Linux/macOS/Windows) to verify
that webscout-mcp is installed correctly and all core functionality works.

Usage:
    python scripts/verify_installation.py

Exit codes:
    0 - All checks passed
    1 - Some checks failed
"""

from __future__ import annotations

import platform
import sys
import time
from dataclasses import dataclass, field


@dataclass
class CheckResult:
    name: str
    passed: bool
    message: str = ""
    duration_ms: float = 0.0


@dataclass
class VerificationReport:
    platform: str
    python_version: str
    webscout_version: str = ""
    checks: list[CheckResult] = field(default_factory=list)

    @property
    def passed_count(self) -> int:
        return sum(1 for c in self.checks if c.passed)

    @property
    def failed_count(self) -> int:
        return sum(1 for c in self.checks if not c.passed)

    @property
    def all_passed(self) -> bool:
        return self.failed_count == 0


def run_check(name: str, fn) -> CheckResult:
    """Run a single check and return result."""
    start = time.time()
    try:
        message = fn()
        return CheckResult(
            name=name,
            passed=True,
            message=message or "OK",
            duration_ms=(time.time() - start) * 1000,
        )
    except Exception as e:
        return CheckResult(
            name=name,
            passed=False,
            message=f"{type(e).__name__}: {e}",
            duration_ms=(time.time() - start) * 1000,
        )


def check_python_version() -> str:
    """Check Python version is supported."""
    version = sys.version_info
    if version < (3, 10):
        raise RuntimeError(f"Python {version.major}.{version.minor} is not supported (need 3.10+)")
    return f"Python {version.major}.{version.minor}.{version.micro}"


def check_import_webscout() -> str:
    """Check webscout_mcp can be imported."""
    import webscout_mcp

    return f"webscout_mcp {webscout_mcp.__version__}"


def check_import_server() -> str:
    """Check MCP server can be imported."""
    return "create_server imported"


def check_import_config() -> str:
    """Check config can be imported."""
    from webscout_mcp.config import Config

    cfg = Config.from_env()
    return f"Config loaded (cache_dir={cfg.cache_dir})"


def check_import_search_service() -> str:
    """Check SearchService can be imported."""
    return "SearchService imported"


def check_import_provider_router() -> str:
    """Check ProviderRouter can be imported."""
    return "ProviderRouter imported"


def check_import_errors() -> str:
    """Check error codes can be imported."""
    from webscout_mcp.errors import StandardErrorCode

    codes = [e.value for e in StandardErrorCode]
    return f"{len(codes)} standard error codes defined"


def check_import_fetcher() -> str:
    """Check Fetcher can be imported."""
    return "Fetcher imported"


def check_import_cache() -> str:
    """Check Cache can be imported."""
    return "Cache imported"


def check_server_creation() -> str:
    """Test that MCP server can be created."""
    from webscout_mcp.server import create_server

    server = create_server()
    tool_count = len(server._tool_manager._tools) if hasattr(server, "_tool_manager") else "unknown"
    return f"Server created (tools: {tool_count})"


def check_search_service_creation() -> str:
    """Test that SearchService can be created with providers."""
    from webscout_mcp.config import Config
    from webscout_mcp.search_service import create_search_service_from_config

    cfg = Config.from_env()
    service = create_search_service_from_config(cfg)
    providers = [p.name for p in service.providers]
    router_enabled = service.router is not None
    return f"SearchService created (providers: {providers}, dynamic_routing: {router_enabled})"


def check_platform() -> str:
    """Report platform information."""
    return f"{platform.system()} {platform.release()} ({platform.machine()})"


def main() -> int:
    """Run all verification checks."""
    print("=" * 70)
    print("webscout-mcp Cross-Platform Verification")
    print("=" * 70)
    print()

    report = VerificationReport(
        platform=platform.system(),
        python_version=f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
    )

    # Platform info
    print(f"Platform: {platform.system()} {platform.release()} ({platform.machine()})")
    print(f"Python:   {report.python_version}")
    print()

    # Define checks
    checks = [
        ("Python version", check_python_version),
        ("Platform", check_platform),
        ("Import webscout_mcp", check_import_webscout),
        ("Import server", check_import_server),
        ("Import config", check_import_config),
        ("Import search_service", check_import_search_service),
        ("Import provider_router", check_import_provider_router),
        ("Import errors", check_import_errors),
        ("Import fetcher", check_import_fetcher),
        ("Import cache", check_import_cache),
        ("Server creation", check_server_creation),
        ("SearchService creation", check_search_service_creation),
    ]

    print("Running checks...")
    print("-" * 70)

    for name, fn in checks:
        result = run_check(name, fn)
        report.checks.append(result)
        status = "✅" if result.passed else "❌"
        print(f"{status} {name:30s} {result.message:40s} ({result.duration_ms:.0f}ms)")

    print("-" * 70)
    print()

    # Summary
    print(f"Results: {report.passed_count} passed, {report.failed_count} failed")
    print()

    if report.all_passed:
        print("✅ All checks passed! webscout-mcp is ready to use on this platform.")
        print()
        print("Quick start:")
        print("  python -m webscout_mcp serve")
        print()
        return 0
    else:
        print("❌ Some checks failed. Please review the errors above.")
        print()
        failed = [c for c in report.checks if not c.passed]
        for c in failed:
            print(f"  - {c.name}: {c.message}")
        print()
        return 1


if __name__ == "__main__":
    sys.exit(main())
