"""Global pytest configuration and fixtures."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))


@pytest.fixture
def sample_html():
    """Sample HTML for testing content extraction."""
    return """
    <!DOCTYPE html>
    <html>
    <head><title>Test Page</title></head>
    <body>
        <article>
            <h1>Test Article</h1>
            <p>This is a test article content for extraction testing.</p>
            <p>Second paragraph with more content here.</p>
        </article>
        <nav><a href="/">Home</a></nav>
    </body>
    </html>
    """


@pytest.fixture
def sample_sitemap_xml():
    """Sample sitemap XML for testing."""
    return """<?xml version="1.0" encoding="UTF-8"?>
    <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
        <url>
            <loc>https://example.com/page1</loc>
            <lastmod>2024-01-15</lastmod>
            <changefreq>weekly</changefreq>
            <priority>0.8</priority>
        </url>
        <url>
            <loc>https://example.com/page2</loc>
            <lastmod>2024-01-20</lastmod>
            <priority>0.5</priority>
        </url>
    </urlset>
    """


def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line(
        "markers", "e2e: mark end-to-end network tests (skipped in CI)"
    )
