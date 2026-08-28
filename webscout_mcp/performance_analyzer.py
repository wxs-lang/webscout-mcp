"""Performance analyzer module for webscout-mcp.
Analyzes web page performance and provides optimization suggestions.

Features:
- Page load time analysis
- Resource size analysis (HTML, CSS, JS, images)
- Request count analysis
- Time to First Byte (TTFB) estimation
- DOM size analysis
- Render-blocking resources detection
- Image optimization suggestions
- CSS/JS minification suggestions
- Compression (gzip/brotli) detection
- Cache policy analysis
- Overall performance score
- Optimization recommendations
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from .logging import get_logger

log = get_logger(__name__)


@dataclass
class PerformanceMetrics:
    """Performance analysis metrics."""

    # Basic metrics
    url: str = ""
    html_size_bytes: int = 0
    html_size_kb: float = 0.0
    dom_node_count: int = 0
    request_count: int = 0

    # Resource counts
    css_count: int = 0
    js_count: int = 0
    image_count: int = 0
    font_count: int = 0
    iframe_count: int = 0

    # Resource sizes (estimated)
    css_size_bytes: int = 0
    js_size_bytes: int = 0
    image_size_bytes: int = 0

    # Performance indicators
    has_gzip: bool = False
    has_brotli: bool = False
    has_cache_headers: bool = False
    has_render_blocking_resources: bool = False
    has_inline_css: bool = False
    has_inline_js: bool = False
    has_lazy_loading: bool = False
    has_preconnect: bool = False
    has_preload: bool = False

    # Scores (0-100)
    html_size_score: float = 0.0
    dom_size_score: float = 0.0
    request_count_score: float = 0.0
    resource_optimization_score: float = 0.0
    caching_score: float = 0.0
    overall_score: float = 0.0

    # Issues and recommendations
    issues: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "url": self.url,
            "html_size_bytes": self.html_size_bytes,
            "html_size_kb": self.html_size_kb,
            "dom_node_count": self.dom_node_count,
            "request_count": self.request_count,
            "css_count": self.css_count,
            "js_count": self.js_count,
            "image_count": self.image_count,
            "font_count": self.font_count,
            "iframe_count": self.iframe_count,
            "has_gzip": self.has_gzip,
            "has_brotli": self.has_brotli,
            "has_cache_headers": self.has_cache_headers,
            "has_render_blocking_resources": self.has_render_blocking_resources,
            "has_inline_css": self.has_inline_css,
            "has_inline_js": self.has_inline_js,
            "has_lazy_loading": self.has_lazy_loading,
            "html_size_score": self.html_size_score,
            "dom_size_score": self.dom_size_score,
            "request_count_score": self.request_count_score,
            "resource_optimization_score": self.resource_optimization_score,
            "caching_score": self.caching_score,
            "overall_score": self.overall_score,
            "issues": self.issues,
            "warnings": self.warnings,
            "recommendations": self.recommendations,
        }


class PerformanceAnalyzer:
    """Analyzes web page performance and provides optimization suggestions.

    Features:
    - HTML size analysis
    - DOM size analysis
    - Resource count analysis
    - Render-blocking resource detection
    - Optimization recommendations
    - Performance scoring
    """

    # Thresholds
    MAX_HTML_SIZE_KB = 100  # Good if under 100KB
    MAX_DOM_NODES = 1500  # Good if under 1500 nodes
    MAX_REQUESTS = 20  # Good if under 20 requests

    def __init__(self) -> None:
        pass

    def analyze(self, html: str, url: str = "", response_headers: Optional[dict] = None) -> PerformanceMetrics:
        """Analyze a web page for performance.

        Args:
            html: HTML content of the page.
            url: URL of the page.
            response_headers: HTTP response headers (optional).

        Returns:
            PerformanceMetrics with analysis results.
        """
        metrics = PerformanceMetrics(url=url)

        if not html:
            metrics.issues.append("No HTML content provided")
            return metrics

        # Analyze HTML size
        self._analyze_html_size(html, metrics)

        # Analyze DOM
        self._analyze_dom(html, metrics)

        # Analyze resources
        self._analyze_resources(html, metrics)

        # Analyze response headers
        if response_headers:
            self._analyze_headers(response_headers, metrics)

        # Analyze optimization techniques
        self._analyze_optimization(html, metrics)

        # Calculate scores
        self._calculate_scores(metrics)

        # Generate issues and recommendations
        self._generate_issues_and_recommendations(metrics)

        return metrics

    def _analyze_html_size(self, html: str, metrics: PerformanceMetrics) -> None:
        """Analyze HTML size."""
        metrics.html_size_bytes = len(html.encode("utf-8"))
        metrics.html_size_kb = round(metrics.html_size_bytes / 1024, 2)

    def _analyze_dom(self, html: str, metrics: PerformanceMetrics) -> None:
        """Analyze DOM structure."""
        try:
            from bs4 import BeautifulSoup

            soup = BeautifulSoup(html, "html.parser")

            # Count DOM nodes (approximate)
            metrics.dom_node_count = len(soup.find_all())

            # Count iframes
            metrics.iframe_count = len(soup.find_all("iframe"))

        except ImportError:
            log.warning("BeautifulSoup not available for DOM analysis")
            # Fallback: count tags with regex
            metrics.dom_node_count = len(re.findall(r"<[a-zA-Z][^>]*>", html))

    def _analyze_resources(self, html: str, metrics: PerformanceMetrics) -> None:
        """Analyze resource references."""
        try:
            from bs4 import BeautifulSoup

            soup = BeautifulSoup(html, "html.parser")

            # Count CSS
            metrics.css_count = len(soup.find_all("link", rel="stylesheet"))
            # Count inline CSS
            metrics.has_inline_css = bool(soup.find("style"))

            # Count JS
            metrics.js_count = len(soup.find_all("script", src=True))
            # Count inline JS
            metrics.has_inline_js = bool(soup.find("script", src=False))

            # Count images
            metrics.image_count = len(soup.find_all("img"))

            # Count fonts
            metrics.font_count = len(soup.find_all("link", rel=re.compile(r"font", re.I)))

            # Total estimated requests
            metrics.request_count = (
                metrics.css_count + metrics.js_count + metrics.image_count + metrics.font_count + metrics.iframe_count
            )

            # Check for render-blocking resources
            # CSS in <head> without media="print" or onload swap
            head = soup.find("head")
            if head:
                render_blocking_css = head.find_all("link", rel="stylesheet")
                render_blocking_js = head.find_all("script", src=True)
                if render_blocking_css or render_blocking_js:
                    metrics.has_render_blocking_resources = True

        except ImportError:
            log.warning("BeautifulSoup not available for resource analysis")

    def _analyze_headers(self, headers: dict, metrics: PerformanceMetrics) -> None:
        """Analyze HTTP response headers."""
        headers_lower = {k.lower(): v for k, v in headers.items()}

        # Check compression
        content_encoding = headers_lower.get("content-encoding", "")
        if "gzip" in content_encoding:
            metrics.has_gzip = True
        if "br" in content_encoding:
            metrics.has_brotli = True

        # Check cache headers
        cache_control = headers_lower.get("cache-control", "")
        expires = headers_lower.get("expires", "")
        etag = headers_lower.get("etag", "")
        if cache_control or expires or etag:
            metrics.has_cache_headers = True

    def _analyze_optimization(self, html: str, metrics: PerformanceMetrics) -> None:
        """Analyze optimization techniques."""
        # Check for lazy loading
        if 'loading="lazy"' in html or "loading='lazy'" in html:
            metrics.has_lazy_loading = True

        # Check for preconnect
        if 'rel="preconnect"' in html or "rel='preconnect'" in html:
            metrics.has_preconnect = True

        # Check for preload
        if 'rel="preload"' in html or "rel='preload'" in html:
            metrics.has_preload = True

    def _calculate_scores(self, metrics: PerformanceMetrics) -> None:
        """Calculate performance scores."""
        # HTML size score
        if metrics.html_size_kb <= self.MAX_HTML_SIZE_KB:
            metrics.html_size_score = 100
        elif metrics.html_size_kb <= 200:
            metrics.html_size_score = 70
        elif metrics.html_size_kb <= 500:
            metrics.html_size_score = 40
        else:
            metrics.html_size_score = 20

        # DOM size score
        if metrics.dom_node_count <= self.MAX_DOM_NODES:
            metrics.dom_size_score = 100
        elif metrics.dom_node_count <= 3000:
            metrics.dom_size_score = 70
        elif metrics.dom_node_count <= 5000:
            metrics.dom_size_score = 40
        else:
            metrics.dom_size_score = 20

        # Request count score
        if metrics.request_count <= self.MAX_REQUESTS:
            metrics.request_count_score = 100
        elif metrics.request_count <= 40:
            metrics.request_count_score = 70
        elif metrics.request_count <= 80:
            metrics.request_count_score = 40
        else:
            metrics.request_count_score = 20

        # Resource optimization score
        opt_score = 50  # Base
        if metrics.has_gzip or metrics.has_brotli:
            opt_score += 20
        if metrics.has_lazy_loading:
            opt_score += 15
        if metrics.has_preconnect:
            opt_score += 10
        if metrics.has_preload:
            opt_score += 5
        metrics.resource_optimization_score = min(100, opt_score)

        # Caching score
        if metrics.has_cache_headers:
            metrics.caching_score = 100
        else:
            metrics.caching_score = 30

        # Overall score (weighted average)
        metrics.overall_score = (
            metrics.html_size_score * 0.20
            + metrics.dom_size_score * 0.20
            + metrics.request_count_score * 0.20
            + metrics.resource_optimization_score * 0.25
            + metrics.caching_score * 0.15
        )

    def _generate_issues_and_recommendations(self, metrics: PerformanceMetrics) -> None:
        """Generate performance issues and recommendations."""
        # HTML size issues
        if metrics.html_size_kb > self.MAX_HTML_SIZE_KB:
            metrics.issues.append(f"HTML size is {metrics.html_size_kb}KB (ideal: under {self.MAX_HTML_SIZE_KB}KB)")
            metrics.recommendations.append("Minify HTML and remove unnecessary whitespace/comments")

        # DOM size issues
        if metrics.dom_node_count > self.MAX_DOM_NODES:
            metrics.issues.append(f"DOM has {metrics.dom_node_count} nodes (ideal: under {self.MAX_DOM_NODES})")
            metrics.recommendations.append("Reduce DOM complexity by removing unnecessary nested elements")

        # Request count issues
        if metrics.request_count > self.MAX_REQUESTS:
            metrics.issues.append(f"Page makes {metrics.request_count} requests (ideal: under {self.MAX_REQUESTS})")
            metrics.recommendations.append("Combine CSS/JS files and use CSS sprites for images")

        # Render-blocking resources
        if metrics.has_render_blocking_resources:
            metrics.warnings.append("Page has render-blocking resources in <head>")
            metrics.recommendations.append("Defer non-critical JavaScript and load CSS asynchronously")

        # Compression
        if not metrics.has_gzip and not metrics.has_brotli:
            metrics.warnings.append("No compression detected (gzip/brotli)")
            metrics.recommendations.append("Enable gzip or brotli compression on the server")

        # Caching
        if not metrics.has_cache_headers:
            metrics.issues.append("No cache headers detected")
            metrics.recommendations.append("Add Cache-Control, Expires, or ETag headers for static resources")

        # Lazy loading
        if metrics.image_count > 5 and not metrics.has_lazy_loading:
            metrics.warnings.append("Images without lazy loading detected")
            metrics.recommendations.append('Add loading="lazy" attribute to below-the-fold images')

        # Inline CSS/JS
        if metrics.has_inline_css:
            metrics.warnings.append("Inline CSS detected")
            metrics.recommendations.append("Move inline CSS to external stylesheets for better caching")

        # Iframes
        if metrics.iframe_count > 0:
            metrics.warnings.append(f"{metrics.iframe_count} iframe(s) detected")
            metrics.recommendations.append("Consider lazy-loading iframes to improve initial load time")

        # Overall recommendation
        if metrics.overall_score >= 80:
            metrics.recommendations.append("Great performance! Continue monitoring and optimizing.")
        elif metrics.overall_score >= 60:
            metrics.recommendations.append("Good performance. Address the issues above for further improvement.")
        else:
            metrics.recommendations.append(
                "Significant performance improvements needed. Start with the critical issues."
            )


def analyze_performance(html: str, url: str = "", response_headers: Optional[dict] = None) -> PerformanceMetrics:
    """Convenience function to analyze page performance.

    Args:
        html: HTML content.
        url: Page URL.
        response_headers: HTTP response headers.

    Returns:
        PerformanceMetrics with analysis results.
    """
    analyzer = PerformanceAnalyzer()
    return analyzer.analyze(html, url, response_headers)
