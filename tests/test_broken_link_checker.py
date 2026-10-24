"""Tests for broken link checker module."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, call, patch

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

    def test_fetch_page_html_blocks_private_target_before_client_creation(self):
        checker = BrokenLinkChecker()
        with patch("httpx.AsyncClient") as client_factory:
            html, final_url, error = asyncio.run(checker.fetch_page_html("http://127.0.0.1/admin"))

        assert html is None
        assert final_url == "http://127.0.0.1/admin"
        assert "SSRF blocked" in error
        client_factory.assert_not_called()

    def test_fetch_page_html_pins_start_url_and_preserves_host_and_sni(self):
        checker = BrokenLinkChecker()
        page_url = "https://public.example/start?q=1"
        response = MagicMock()
        response.status_code = 200
        response.headers = {}
        response.encoding = "utf-8"
        response.aclose = AsyncMock()

        async def aiter_bytes():
            yield b"<html><body>start page</body></html>"

        response.aiter_bytes = aiter_bytes
        client = MagicMock()
        client.build_request.side_effect = lambda method, url, headers: __import__("httpx").Request(
            method, url, headers=headers
        )
        client.send = AsyncMock(return_value=response)
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=False)
        client_factory = MagicMock(return_value=client)

        with (
            patch("webscout_mcp.broken_link_checker.check_url_safe") as safety_check,
            patch("httpx.AsyncClient", client_factory),
        ):
            safety_check.return_value = SimpleNamespace(safe=True, reason="ok", resolved_ips=["93.184.216.34"])
            html, final_url, error = asyncio.run(checker.fetch_page_html(page_url))

        assert error is None
        assert final_url == page_url
        assert "start page" in html
        request = client.send.call_args.args[0]
        assert str(request.url) == "https://93.184.216.34/start?q=1"
        assert request.headers["host"] == "public.example"
        assert request.extensions["sni_hostname"] == "public.example"
        client.send.assert_awaited_once_with(request, follow_redirects=False, stream=True)
        assert safety_check.call_args_list == [call(page_url)]

    def test_fetch_page_html_blocks_redirect_to_private_before_second_request(self):
        checker = BrokenLinkChecker()
        page_url = "https://public.example/redirect"
        private_url = "http://127.0.0.1/admin"
        response = MagicMock()
        response.status_code = 302
        response.headers = {"Location": private_url}
        response.encoding = "utf-8"
        response.aclose = AsyncMock()

        async def aiter_bytes():
            yield b""

        response.aiter_bytes = aiter_bytes
        client = MagicMock()
        client.build_request.side_effect = lambda method, url, headers: __import__("httpx").Request(
            method, url, headers=headers
        )
        client.send = AsyncMock(return_value=response)
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=False)
        client_factory = MagicMock(return_value=client)

        with (
            patch("webscout_mcp.broken_link_checker.check_url_safe") as safety_check,
            patch("httpx.AsyncClient", client_factory),
        ):
            safety_check.side_effect = [
                SimpleNamespace(safe=True, reason="ok", resolved_ips=["93.184.216.34"]),
                SimpleNamespace(safe=False, reason="private address", resolved_ips=None),
            ]
            html, final_url, error = asyncio.run(checker.fetch_page_html(page_url))

        assert html is None
        assert final_url == private_url
        assert "private address" in error
        client.send.assert_awaited_once()
        request = client.send.call_args.args[0]
        assert str(request.url) == "https://93.184.216.34/redirect"
        assert request.headers["host"] == "public.example"
        assert request.extensions["sni_hostname"] == "public.example"
        assert safety_check.call_args_list == [call(page_url), call(private_url)]

    def test_request_uses_resolved_public_ip_and_preserves_host_and_sni(self):
        checker = BrokenLinkChecker()
        origin_url = "https://public.example/path?q=1"
        response = MagicMock()
        response.status_code = 200
        http_client = MagicMock()
        http_client.build_request.side_effect = lambda method, url, headers: __import__("httpx").Request(
            method, url, headers=headers
        )
        http_client.send.return_value = response
        client_factory = MagicMock()
        client_factory.return_value.__enter__.return_value = http_client

        with (
            patch("webscout_mcp.broken_link_checker.check_url_safe") as safety_check,
            patch("httpx.Client", client_factory),
        ):
            safety_check.return_value = SimpleNamespace(
                safe=True, reason="ok", resolved_ips=["93.184.216.34", "2606:2800:220:1:248:1893:25c8:1946"]
            )
            result = checker.check_link(origin_url)

        assert result.status == "ok"
        request = http_client.send.call_args.args[0]
        assert str(request.url) == "https://93.184.216.34/path?q=1"
        assert request.headers["host"] == "public.example"
        assert request.extensions["sni_hostname"] == "public.example"
        http_client.send.assert_called_once_with(request, follow_redirects=False)

    def test_max_redirects_allows_request_to_final_destination(self):
        checker = BrokenLinkChecker(max_redirects=1)
        initial_url = "https://public.example/start"
        final_url = "https://public.example/final"

        redirect_response = MagicMock()
        redirect_response.status_code = 302
        redirect_response.headers = {"Location": final_url}
        final_response = MagicMock()
        final_response.status_code = 200

        http_client = MagicMock()
        http_client.build_request.side_effect = lambda method, url, headers: __import__("httpx").Request(
            method, url, headers=headers
        )
        http_client.send.side_effect = [redirect_response, final_response]
        client_factory = MagicMock()
        client_factory.return_value.__enter__.return_value = http_client

        with (
            patch("webscout_mcp.broken_link_checker.check_url_safe") as safety_check,
            patch("httpx.Client", client_factory),
        ):
            safety_check.side_effect = [
                SimpleNamespace(safe=True, reason="ok", resolved_ips=["93.184.216.34"]),
                SimpleNamespace(safe=True, reason="ok", resolved_ips=["93.184.216.34"]),
            ]
            result = checker.check_link(initial_url)

        assert result.status == "redirect"
        assert result.final_url == final_url
        assert result.redirect_count == 1
        assert result.redirect_chain == [initial_url, final_url]
        assert http_client.send.call_count == 2

    def test_private_network_url_is_blocked_before_request(self):
        checker = BrokenLinkChecker()

        with patch("httpx.Client") as client_factory:
            result = checker.check_link("http://127.0.0.1/admin")

        assert result.status == "blocked"
        assert "SSRF blocked" in result.error_message
        assert result.final_url == "http://127.0.0.1/admin"
        client_factory.assert_not_called()

    def test_redirect_to_private_network_is_blocked_before_following(self):
        checker = BrokenLinkChecker()
        initial_url = "https://public.example/redirect"
        private_url = "http://127.0.0.1/admin"

        response = MagicMock()
        response.status_code = 302
        response.headers = {"Location": private_url}
        http_client = MagicMock()
        http_client.build_request.side_effect = lambda method, url, headers: __import__("httpx").Request(
            method, url, headers=headers
        )
        http_client.send.return_value = response
        client_factory = MagicMock()
        client_factory.return_value.__enter__.return_value = http_client

        with (
            patch("webscout_mcp.broken_link_checker.check_url_safe") as safety_check,
            patch("httpx.Client", client_factory),
        ):
            safety_check.side_effect = [
                SimpleNamespace(safe=True, reason="ok", resolved_ips=["93.184.216.34"]),
                SimpleNamespace(safe=False, reason="private address", resolved_ips=None),
            ]
            result = checker.check_link(initial_url)

        assert result.status == "blocked"
        assert result.final_url == private_url
        assert result.redirect_chain == [initial_url, private_url]
        assert "private address" in result.error_message
        http_client.get.assert_not_called()
        http_client.send.assert_called_once()
        request = http_client.send.call_args.args[0]
        assert str(request.url) == "https://93.184.216.34/redirect"
        assert request.headers["host"] == "public.example"
        assert request.extensions["sni_hostname"] == "public.example"
        assert http_client.send.call_args.kwargs["follow_redirects"] is False
        assert safety_check.call_args_list == [call(initial_url), call(private_url)]

    def test_check_page_counts_ssrf_blocked_links(self):
        checker = BrokenLinkChecker()
        html = '<html><body><a href="http://127.0.0.1/admin">Local admin</a></body></html>'

        report = checker.check_page(html, base_url="https://public.example/")

        assert report.total_links == 1
        assert report.blocked_links == 1
        assert report.results[0].status == "blocked"
        assert "Blocked (SSRF safety): 1" in checker.generate_summary(report)

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
