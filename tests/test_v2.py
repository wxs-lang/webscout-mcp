"""Tests for v0.2.0 features: exceptions, logging, robots.txt,
multi-backend search, config fields, and CLI parser.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from webscout_mcp.config import Config
from webscout_mcp.exceptions import (
    AllBackendsFailedError,
    ContentTooLargeError,
    DisallowedByRobotsError,
    FetchError,
    ForbiddenError,
    HTTPError,
    NotFoundError,
    SearchError,
    TimeoutError,
    WebScoutError,
)
from webscout_mcp.search import (
    BingBackend,
    DuckDuckGoHTMLBackend,
    SearchResult,
)


# --- Exceptions ---


class TestExceptions:
    def test_base_exception(self):
        exc = WebScoutError("test")
        assert str(exc) == "test"
        assert isinstance(exc, Exception)

    def test_fetch_error(self):
        exc = FetchError("https://example.com")
        assert exc.url == "https://example.com"
        assert "https://example.com" in str(exc)

    def test_timeout_error(self):
        exc = TimeoutError("https://example.com", timeout=15.0)
        assert exc.timeout == 15.0
        assert "15.0s" in str(exc)

    def test_http_error(self):
        exc = HTTPError("https://example.com", 500)
        assert exc.status_code == 500
        assert "500" in str(exc)

    def test_forbidden_error(self):
        exc = ForbiddenError("https://example.com")
        assert exc.status_code == 403
        assert "403" in str(exc)

    def test_not_found_error(self):
        exc = NotFoundError("https://example.com")
        assert exc.status_code == 404
        assert "404" in str(exc)

    def test_content_too_large(self):
        exc = ContentTooLargeError("https://example.com", 10000, 5000)
        assert exc.content_length == 10000
        assert exc.max_length == 5000
        assert "10000" in str(exc)

    def test_search_error(self):
        exc = SearchError("test query", backend="bing", message="failed")
        assert exc.query == "test query"
        assert exc.backend == "bing"
        assert "failed" in str(exc)

    def test_search_error_default_message(self):
        exc = SearchError("test query")
        assert "test query" in str(exc)

    def test_all_backends_failed(self):
        failures = {"bing": "timeout", "duckduckgo": "403"}
        exc = AllBackendsFailedError("test", failures)
        assert exc.failures == failures
        assert "bing" in str(exc)
        assert "duckduckgo" in str(exc)

    def test_disallowed_by_robots(self):
        exc = DisallowedByRobotsError("https://example.com/private", "webscout")
        assert exc.url == "https://example.com/private"
        assert exc.user_agent == "webscout"
        assert "robots.txt" in str(exc)

    def test_exception_hierarchy(self):
        """All custom exceptions inherit from WebScoutError."""
        assert issubclass(FetchError, WebScoutError)
        assert issubclass(TimeoutError, FetchError)
        assert issubclass(HTTPError, FetchError)
        assert issubclass(ForbiddenError, HTTPError)
        assert issubclass(NotFoundError, HTTPError)
        assert issubclass(ContentTooLargeError, FetchError)
        assert issubclass(SearchError, WebScoutError)
        assert issubclass(AllBackendsFailedError, SearchError)
        assert issubclass(DisallowedByRobotsError, WebScoutError)


# --- Config new fields ---


class TestConfigNewFields:
    def test_crawler_concurrency_default(self):
        cfg = Config()
        assert cfg.crawler_concurrency == 5

    def test_respect_robots_default(self):
        cfg = Config()
        assert cfg.respect_robots is True

    def test_crawler_concurrency_from_env(self, monkeypatch):
        monkeypatch.setenv("WEBSCOUT_CRAWLER_CONCURRENCY", "10")
        cfg = Config.from_env()
        assert cfg.crawler_concurrency == 10

    def test_respect_robots_from_env(self, monkeypatch):
        monkeypatch.setenv("WEBSCOUT_RESPECT_ROBOTS", "false")
        cfg = Config.from_env()
        assert cfg.respect_robots is False

    def test_respect_robots_from_env_true(self, monkeypatch):
        monkeypatch.setenv("WEBSCOUT_RESPECT_ROBOTS", "1")
        cfg = Config.from_env()
        assert cfg.respect_robots is True


# --- Search backend parsing ---


class TestBingBackendParsing:
    SAMPLE_HTML = """
    <html><body>
    <li class="b_algo">
        <h2><a href="https://example.com/page1">Example Page 1</a></h2>
        <div class="b_caption"><p>This is the first result snippet.</p></div>
    </li>
    <li class="b_algo">
        <h2><a href="https://example.com/page2">Example Page 2</a></h2>
        <p>Second result snippet here.</p>
    </li>
    <li class="b_algo">
        <h2><a href="/internal/link">Internal Link</a></h2>
        <p>Should be skipped (not http).</p>
    </li>
    </body></html>
    """

    def test_parse_basic(self):
        results = BingBackend._parse_results(self.SAMPLE_HTML, 10)
        assert len(results) == 2  # third is skipped (non-http)
        assert results[0].title == "Example Page 1"
        assert results[0].url == "https://example.com/page1"
        assert results[0].snippet == "This is the first result snippet."
        assert results[0].position == 1
        assert results[0].backend == "bing"

    def test_parse_max_results(self):
        results = BingBackend._parse_results(self.SAMPLE_HTML, 1)
        assert len(results) == 1

    def test_parse_empty_html(self):
        results = BingBackend._parse_results("<html></html>", 10)
        assert len(results) == 0


class TestDuckDuckGoBackendParsing:
    SAMPLE_HTML = """
    <html><body>
    <div class="result">
        <a class="result__a" href="https://example.com/page1">DDG Result 1</a>
        <a class="result__snippet">First DDG snippet.</a>
    </div>
    <div class="result">
        <a class="result__a" href="/l/?uddg=https%3A%2F%2Fexample.com%2Fpage2&rut=abc">DDG Result 2</a>
        <div class="result__snippet">Second DDG snippet.</div>
    </div>
    </body></html>
    """

    def test_parse_basic(self):
        results = DuckDuckGoHTMLBackend._parse_results(self.SAMPLE_HTML, 10)
        assert len(results) == 2
        assert results[0].title == "DDG Result 1"
        assert results[0].url == "https://example.com/page1"
        assert results[0].snippet == "First DDG snippet."
        assert results[0].backend == "duckduckgo"

    def test_extract_real_url_redirect(self):
        url = "/l/?uddg=https%3A%2F%2Fexample.com%2Fpath%3Fq%3D1&rut=abc"
        result = DuckDuckGoHTMLBackend._extract_real_url(url)
        assert result == "https://example.com/path?q=1"

    def test_extract_real_url_direct(self):
        url = "https://example.com/direct"
        assert DuckDuckGoHTMLBackend._extract_real_url(url) == url

    def test_parse_max_results(self):
        results = DuckDuckGoHTMLBackend._parse_results(self.SAMPLE_HTML, 1)
        assert len(results) == 1


# --- RobotsChecker ---


class TestRobotsChecker:
    def test_respect_robots_false(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = Config(cache_dir=Path(tmpdir))
            from webscout_mcp.robots import RobotsChecker

            checker = RobotsChecker(cfg, respect_robots=False)
            # Should always return True when respect_robots is False
            import asyncio

            result = asyncio.run(checker.is_allowed("https://example.com/private"))
            assert result is True

    def test_clear_cache(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = Config(cache_dir=Path(tmpdir))
            from webscout_mcp.robots import RobotsChecker

            checker = RobotsChecker(cfg)
            checker._cache["test"] = MagicMock()
            checker.clear_cache()
            assert len(checker._cache) == 0


# --- Logging ---


class TestLogging:
    def test_setup_logging(self):
        from webscout_mcp.logging import setup_logging, get_logger

        setup_logging(level="DEBUG")
        log = get_logger("test")
        assert log is not None
        assert log.name == "webscout.test"

    def test_get_logger_auto_init(self):
        from webscout_mcp.logging import get_logger

        # Should not raise even if setup_logging wasn't called
        log = get_logger("auto")
        assert log is not None

    def test_json_formatter(self):
        from webscout_mcp.logging import _JsonFormatter
        import logging

        formatter = _JsonFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg="test message",
            args=(),
            exc_info=None,
        )
        output = formatter.format(record)
        assert "test message" in output
        assert "INFO" in output


# --- CLI parser ---


class TestCLIParser:
    def test_build_parser(self):
        from webscout_mcp.__main__ import build_parser

        parser = build_parser()
        assert parser is not None

    def test_search_subcommand(self):
        from webscout_mcp.__main__ import build_parser

        parser = build_parser()
        args = parser.parse_args(["search", "test query", "--max-results", "5"])
        assert args.command == "search"
        assert args.query == "test query"
        assert args.max_results == 5

    def test_fetch_subcommand(self):
        from webscout_mcp.__main__ import build_parser

        parser = build_parser()
        args = parser.parse_args(
            ["fetch", "https://example.com", "--format", "text", "--raw"]
        )
        assert args.command == "fetch"
        assert args.url == "https://example.com"
        assert args.format == "text"
        assert args.raw is True

    def test_crawl_subcommand(self):
        from webscout_mcp.__main__ import build_parser

        parser = build_parser()
        args = parser.parse_args(
            ["crawl", "https://example.com", "--depth", "3", "--pages", "20"]
        )
        assert args.command == "crawl"
        assert args.url == "https://example.com"
        assert args.depth == 3
        assert args.pages == 20

    def test_serve_subcommand(self):
        from webscout_mcp.__main__ import build_parser

        parser = build_parser()
        args = parser.parse_args(["serve", "--transport", "sse", "--port", "9000"])
        assert args.command == "serve"
        assert args.transport == "sse"
        assert args.port == 9000

    def test_version_flag(self):
        from webscout_mcp.__main__ import build_parser
        from webscout_mcp import __version__

        parser = build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["--version"])
