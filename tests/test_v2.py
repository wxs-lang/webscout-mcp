"""Tests for v0.2.0 features: exceptions, logging, robots.txt, multi-backend search, concurrent crawler, CLI."""
from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))


# --- Exception tests ---

class TestExceptions:
    def test_webscout_error_base(self):
        from webscout_mcp.exceptions import WebScoutError
        err = WebScoutError("test")
        assert isinstance(err, Exception)
        assert str(err) == "test"

    def test_fetch_error(self):
        from webscout_mcp.exceptions import FetchError
        err = FetchError("https://example.com")
        assert err.url == "https://example.com"
        assert "Failed to fetch" in str(err)

    def test_timeout_error(self):
        from webscout_mcp.exceptions import TimeoutError
        err = TimeoutError("https://example.com", timeout=10.0)
        assert err.timeout == 10.0
        assert "timed out" in str(err)

    def test_http_error(self):
        from webscout_mcp.exceptions import HTTPError
        err = HTTPError("https://example.com", 500)
        assert err.status_code == 500
        assert "500" in str(err)

    def test_forbidden_error(self):
        from webscout_mcp.exceptions import ForbiddenError
        err = ForbiddenError("https://example.com")
        assert err.status_code == 403

    def test_not_found_error(self):
        from webscout_mcp.exceptions import NotFoundError
        err = NotFoundError("https://example.com")
        assert err.status_code == 404

    def test_content_too_large_error(self):
        from webscout_mcp.exceptions import ContentTooLargeError
        err = ContentTooLargeError("https://example.com", 10000, 5000)
        assert err.content_length == 10000
        assert err.max_length == 5000

    def test_search_error(self):
        from webscout_mcp.exceptions import SearchError
        err = SearchError("test query", backend="bing")
        assert err.query == "test query"
        assert err.backend == "bing"

    def test_all_backends_failed_error(self):
        from webscout_mcp.exceptions import AllBackendsFailedError
        failures = {"bing": "timeout", "duckduckgo": "blocked"}
        err = AllBackendsFailedError("test", failures)
        assert err.failures == failures
        assert "bing" in str(err)
        assert "duckduckgo" in str(err)

    def test_disallowed_by_robots_error(self):
        from webscout_mcp.exceptions import DisallowedByRobotsError
        err = DisallowedByRobotsError("https://example.com/private")
        assert err.url == "https://example.com/private"
        assert "robots.txt" in str(err)

    def test_extraction_error(self):
        from webscout_mcp.exceptions import ExtractionError
        err = ExtractionError("title")
        assert err.rule_name == "title"

    def test_crawl_error(self):
        from webscout_mcp.exceptions import CrawlError
        err = CrawlError("crawl failed")
        assert isinstance(err, Exception)


# --- Config tests ---

class TestConfigV2:
    def test_default_values(self):
        from webscout_mcp.config import Config
        config = Config()
        assert config.crawler_concurrency == 5
        assert config.respect_robots is True

    def test_from_env_concurrency(self):
        from webscout_mcp.config import Config
        with patch.dict(os.environ, {"WEBSCOUT_CRAWLER_CONCURRENCY": "10"}):
            config = Config.from_env()
            assert config.crawler_concurrency == 10

    def test_from_env_respect_robots_false(self):
        from webscout_mcp.config import Config
        with patch.dict(os.environ, {"WEBSCOUT_RESPECT_ROBOTS": "false"}):
            config = Config.from_env()
            assert config.respect_robots is False

    def test_from_env_respect_robots_true(self):
        from webscout_mcp.config import Config
        with patch.dict(os.environ, {"WEBSCOUT_RESPECT_ROBOTS": "1"}):
            config = Config.from_env()
            assert config.respect_robots is True


# --- Logging tests ---

class TestLogging:
    def test_get_logger(self):
        from webscout_mcp.logging import get_logger
        log = get_logger("test")
        assert log.name == "webscout.test"

    def test_get_logger_main(self):
        from webscout_mcp.logging import get_logger
        log = get_logger("__main__")
        assert log.name == "webscout"

    def test_setup_logging_json(self):
        from webscout_mcp.logging import setup_logging
        setup_logging(level="DEBUG", json_format=True)
        import logging
        root = logging.getLogger("webscout")
        assert root.level == logging.DEBUG

    def test_setup_logging_console(self):
        from webscout_mcp.logging import setup_logging
        setup_logging(level="INFO", json_format=False)
        import logging
        root = logging.getLogger("webscout")
        assert root.level == logging.INFO


# --- Bing parser tests ---

class TestBingParser:
    def test_parse_bing_html(self):
        from webscout_mcp.search import BingBackend
        html = """
        <html><body>
        <li class="b_algo">
            <h2><a href="https://example.com">Example Title</a></h2>
            <div class="b_caption"><p>This is a snippet</p></div>
        </li>
        <li class="b_algo">
            <h2><a href="https://test.com">Test Title</a></h2>
            <p>Another snippet</p>
        </li>
        </body></html>
        """
        results = BingBackend._parse_results(html, 10)
        assert len(results) == 2
        assert results[0].title == "Example Title"
        assert results[0].url == "https://example.com"
        assert results[0].snippet == "This is a snippet"
        assert results[0].backend == "bing"
        assert results[1].title == "Test Title"

    def test_parse_bing_html_max_results(self):
        from webscout_mcp.search import BingBackend
        html = """
        <html><body>
        <li class="b_algo"><h2><a href="https://1.com">1</a></h2></li>
        <li class="b_algo"><h2><a href="https://2.com">2</a></h2></li>
        <li class="b_algo"><h2><a href="https://3.com">3</a></h2></li>
        </body></html>
        """
        results = BingBackend._parse_results(html, 2)
        assert len(results) == 2

    def test_parse_bing_html_empty(self):
        from webscout_mcp.search import BingBackend
        results = BingBackend._parse_results("<html><body></body></html>", 10)
        assert len(results) == 0


# --- DuckDuckGo parser tests ---

class TestDuckDuckGoParser:
    def test_extract_real_url_direct(self):
        from webscout_mcp.search import DuckDuckGoHTMLBackend
        url = "https://example.com/page"
        assert DuckDuckGoHTMLBackend._extract_real_url(url) == url

    def test_extract_real_url_redirect(self):
        from webscout_mcp.search import DuckDuckGoHTMLBackend
        ddg_url = "/l/?uddg=https%3A%2F%2Fexample.com%2Fpage&rut=abc"
        result = DuckDuckGoHTMLBackend._extract_real_url(ddg_url)
        assert result == "https://example.com/page"

    def test_parse_ddg_html(self):
        from webscout_mcp.search import DuckDuckGoHTMLBackend
        html = """
        <html><body>
        <div class="result">
            <a class="result__a" href="/l/?uddg=https%3A%2F%2Fexample.com">Example</a>
            <a class="result__snippet">This is a snippet</a>
        </div>
        </body></html>
        """
        results = DuckDuckGoHTMLBackend._parse_results(html, 10)
        assert len(results) == 1
        assert results[0].title == "Example"
        assert results[0].url == "https://example.com"
        assert results[0].snippet == "This is a snippet"
        assert results[0].backend == "duckduckgo"


# --- Robots.txt tests ---

class TestRobotsChecker:
    @pytest.mark.asyncio
    async def test_respect_robots_false(self):
        from webscout_mcp.config import Config
        from webscout_mcp.robots import RobotsChecker
        config = Config()
        checker = RobotsChecker(config, respect_robots=False)
        allowed = await checker.is_allowed("https://example.com/any")
        assert allowed is True
        await checker.close()

    @pytest.mark.asyncio
    async def test_domain_extraction(self):
        from webscout_mcp.robots import RobotsChecker
        domain = RobotsChecker._domain("https://example.com/path?q=1")
        assert domain == "https://example.com"

    @pytest.mark.asyncio
    async def test_clear_cache(self):
        from webscout_mcp.config import Config
        from webscout_mcp.robots import RobotsChecker
        config = Config()
        checker = RobotsChecker(config)
        checker._cache["test"] = MagicMock()
        checker.clear_cache()
        assert len(checker._cache) == 0


# --- CLI parser tests ---

class TestCLIParser:
    def test_version(self):
        from webscout_mcp.__main__ import _build_parser
        parser = _build_parser()
        with pytest.raises(SystemExit) as exc_info:
            parser.parse_args(["--version"])
        assert exc_info.value.code == 0

    def test_search_parser(self):
        from webscout_mcp.__main__ import _build_parser
        parser = _build_parser()
        args = parser.parse_args(["search", "test query", "-n", "5"])
        assert args.command == "search"
        assert args.query == "test query"
        assert args.max_results == 5

    def test_fetch_parser(self):
        from webscout_mcp.__main__ import _build_parser
        parser = _build_parser()
        args = parser.parse_args(["fetch", "https://example.com", "--format", "text"])
        assert args.command == "fetch"
        assert args.url == "https://example.com"
        assert args.format == "text"

    def test_crawl_parser(self):
        from webscout_mcp.__main__ import _build_parser
        parser = _build_parser()
        args = parser.parse_args(["crawl", "https://example.com", "--depth", "3", "--concurrency", "10"])
        assert args.command == "crawl"
        assert args.url == "https://example.com"
        assert args.depth == 3
        assert args.concurrency == 10

    def test_serve_parser(self):
        from webscout_mcp.__main__ import _build_parser
        parser = _build_parser()
        args = parser.parse_args(["serve"])
        assert args.command == "serve"
        assert args.transport == "stdio"
