"""Tests for url_safety SSRF guard."""

from __future__ import annotations

import ipaddress
from unittest.mock import patch

import pytest

from webscout_mcp.url_safety import check_url_safe

# --- Literal IP checks ---------------------------------------------------


@pytest.mark.parametrize(
    "ip",
    [
        "1.1.1.1",
        "8.8.8.8",
        "93.184.216.34",  # example.com
    ],
)
def test_public_ip_allowed(ip):
    r = check_url_safe(f"http://{ip}/")
    assert r.safe, r.reason


def test_public_ipv6_allowed():
    r = check_url_safe("http://[2606:4700:4700::1111]/")
    assert r.safe, r.reason


@pytest.mark.parametrize(
    "ip",
    [
        "127.0.0.1",
        "127.0.0.2",
        "127.255.255.255",
        "10.0.0.1",
        "10.255.255.255",
        "172.16.0.1",
        "172.31.255.255",
        "192.168.1.1",
        "192.168.255.255",
        "169.254.169.254",  # cloud metadata
        "169.254.169.253",
        "::1",
        "0.0.0.0",
        "224.0.0.1",
    ],
)
def test_private_or_special_ip_blocked(ip):
    r = check_url_safe(f"http://{ip}/")
    assert not r.safe, f"{ip} should be blocked"


# --- Scheme checks --------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "gopher://127.0.0.1:6379/_INFO",
        "javascript:alert(1)",
        "ftp://example.com/",
    ],
)
def test_non_http_schemes_blocked(url):
    r = check_url_safe(url)
    assert not r.safe


# --- Metadata hostnames ---------------------------------------------------


def test_metadata_hostname_blocked():
    r = check_url_safe("http://metadata.google.internal/computeMetadata/v1/")
    assert not r.safe
    assert "metadata" in r.reason


# --- DNS resolution checks ------------------------------------------------


def test_dns_resolution_to_private_blocked():
    """A hostname that looks public but resolves to 127.0.0.1 must be blocked."""
    with patch("webscout_mcp.url_safety._resolve_host", return_value=["127.0.0.1"]):
        r = check_url_safe("http://evil.example.com/")
    assert not r.safe
    assert "127.0.0.1" in r.resolved_ips or "non-public" in r.reason


def test_dns_resolution_to_public_allowed():
    with patch("webscout_mcp.url_safety._resolve_host", return_value=["93.184.216.34"]):
        r = check_url_safe("http://example.com/")
    assert r.safe


def test_dns_failure_blocks():
    with patch("webscout_mcp.url_safety._resolve_host", return_value=[]):
        r = check_url_safe("http://nonexistent.invalid/")
    assert not r.safe


# --- allow_private opt-in --------------------------------------------------


def test_allow_private_skips_checks():
    r = check_url_safe("http://127.0.0.1/", allow_private=True)
    assert r.safe


# --- Real public domain (integration-ish, uses real DNS) -----------------


def test_real_public_domain_passes():
    r = check_url_safe("https://example.com/")
    assert r.safe, r.reason
    assert r.resolved_ips


def test_real_localhost_blocked():
    r = check_url_safe("http://localhost/")
    assert not r.safe
