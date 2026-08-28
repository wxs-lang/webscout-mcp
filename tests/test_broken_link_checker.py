"""Tests for broken link checker module."""

import pytest

from webscout_mcp.broken_link_checker import (
    BrokenLinkChecker,
    BrokenLinkReport,
    LinkCheckResult,
    check_broken_links,
)


class TestLinkCheckResult:
    """Test LinkCheckResult class."""

    def test_result_creation(self):
        result = LinkCheckResult(url="https://example.com")
        assert result.url == "https://example.com"
        assert result.status == "unknown"
        assert result.status_code == 0

    def test_result_to_dict(self):
        result = LinkCheckResult(
            url="https://example.com",
            status_code=200,
            status="ok",
            anchor_text="Example",
        )
        data = result.to_dict()
        assert data["url"] == "https://example.com"
        assert data["status_code"] == 200
        assert data["status"] == "ok"
        assert data["anchor_text"] == "Example"


class TestBrokenLinkReport:
    """Test BrokenLinkReport class."""

    def test_report_creation(self):
        report = BrokenLinkReport(base_url="https://example.com")
        assert report.base_url == "https://example.com"
        assert report.total_links == 0
        assert report.broken_link_percentage == 0.0

    def test_broken_link_percentage(self):
        report = BrokenLinkReport(total_links=10, broken_links=3)
        assert report.broken_link_percentage == 30.0

    def test_report_to_dict(self):
        report = BrokenLinkReport(
            base_url="https://example.com",
            total_links=5,
            ok_links=4,
            broken_links=1,
        )
        data = report.to_dict()
        assert data["base_url"] == "https://example.com"
        assert data["total_links"] == 5
        assert data["ok_links"] == 4
        assert data["broken_links"] == 1
        assert data["broken_link_percentage"] == 20.0


class TestBrokenLinkChecker:
    """Test BrokenLinkChecker class."""

    def test_checker_creation(self):
        checker = BrokenLinkChecker()
        assert checker.timeout == 10.0
        assert checker.max_redirects == 5

    def test_checker_custom_config(self):
        checker = BrokenLinkChecker(timeout=5.0, max_redirects=3, user_agent="TestBot")
        assert checker.timeout == 5.0
        assert checker.max_redirects == 3
        assert checker.user_agent == "TestBot"

    def test_extract_links(self):
        checker = BrokenLinkChecker()
        html = """
        <html><body>
        <a href="https://example.com/page1">Page 1</a>
        <a href="/page2">Page 2</a>
        <a href="mailto:test@example.com">Email</a>
        <a href="tel:+1234567890">Phone</a>
        <a href="#section">Anchor</a>
        <a href="javascript:void(0)">JS</a>
        </body></html>
        """
        links = checker.extract_links(html, base_url="https://example.com")
        assert len(links) == 6
        # Check that relative URLs are resolved
        assert any(l["url"] == "https://example.com/page2" for l in links)

    def test_classify_link(self):
        checker = BrokenLinkChecker()
        assert checker._classify_link("mailto:test@example.com") == "mailto"
        assert checker._classify_link("tel:+1234567890") == "tel"
        assert checker._classify_link("javascript:void(0)") == "javascript"
        assert checker._classify_link("#section") == "anchor"
        assert checker._classify_link("data:text/plain,test") == "data"
        assert checker._classify_link("https://example.com") == "unknown"

    def test_is_valid_url(self):
        checker = BrokenLinkChecker()
        assert checker._is_valid_url("https://example.com") is True
        assert checker._is_valid_url("http://example.com/path") is True
        assert checker._is_valid_url("mailto:test@example.com") is True
        assert checker._is_valid_url("") is False
        assert checker._is_valid_url("not a url") is False
        assert checker._is_valid_url("ftp://example.com") is False

    def test_check_invalid_url(self):
        checker = BrokenLinkChecker()
        result = checker.check_link("not-a-valid-url")
        assert result.status == "invalid"
        assert "Invalid" in result.error_message

    def test_check_special_links(self):
        checker = BrokenLinkChecker()
        # Mailto links should be OK
        result = checker.check_link("mailto:test@example.com")
        assert result.status == "ok"
        assert result.link_type == "mailto"

        # Tel links should be OK
        result = checker.check_link("tel:+1234567890")
        assert result.status == "ok"
        assert result.link_type == "tel"

    def test_mixed_content_detection(self):
        checker = BrokenLinkChecker()
        # HTTP link on HTTPS page should be flagged
        result = checker.check_link("http://example.com", base_url="https://example.com")
        assert result.is_mixed_content is True

        # HTTPS link on HTTPS page should not be flagged
        result = checker.check_link("https://example.com", base_url="https://example.com")
        assert result.is_mixed_content is False

    def test_internal_external_classification(self):
        checker = BrokenLinkChecker()
        # Same domain should be internal
        result = checker.check_link("https://example.com/page", base_url="https://example.com")
        assert result.link_type == "internal"

        # Different domain should be external
        result = checker.check_link("https://other.com/page", base_url="https://example.com")
        assert result.link_type == "external"

    def test_check_page(self):
        checker = BrokenLinkChecker()
        html = """
        <html><body>
        <a href="https://example.com/valid">Valid</a>
        <a href="mailto:test@example.com">Email</a>
        <a href="ftp://invalid.com">Invalid Protocol</a>
        </body></html>
        """
        report = checker.check_page(html, base_url="https://example.com")
        assert report.total_links == 3
        # ftp:// links should be invalid
        assert report.invalid_links >= 1
        assert len(report.results) == 3

    def test_get_broken_links(self):
        checker = BrokenLinkChecker()
        report = BrokenLinkReport()
        report.results = [
            LinkCheckResult(url="https://ok.com", status="ok"),
            LinkCheckResult(url="https://broken.com", status="broken", status_code=404),
            LinkCheckResult(url="https://timeout.com", status="timeout"),
            LinkCheckResult(url="invalid", status="invalid"),
        ]
        broken = checker.get_broken_links(report)
        assert len(broken) == 3
        assert all(r.status in ("broken", "timeout", "error", "invalid") for r in broken)

    def test_generate_summary(self):
        checker = BrokenLinkChecker()
        report = BrokenLinkReport(
            base_url="https://example.com",
            total_links=10,
            ok_links=8,
            broken_links=2,
        )
        report.results = [
            LinkCheckResult(url="https://broken.com", status="broken", status_code=404, error_message="Not Found"),
        ]
        summary = checker.generate_summary(report)
        assert "Broken Link Check Report" in summary
        assert "https://example.com" in summary
        assert "Total links checked: 10" in summary
        assert "Broken: 2" in summary


class TestConvenienceFunction:
    """Test check_broken_links convenience function."""

    def test_check_broken_links(self):
        html = """
        <html><body>
        <a href="https://example.com">Example</a>
        <a href="invalid">Invalid</a>
        </body></html>
        """
        report = check_broken_links(html, base_url="https://example.com", timeout=5.0)
        assert isinstance(report, BrokenLinkReport)
        assert report.total_links == 2
