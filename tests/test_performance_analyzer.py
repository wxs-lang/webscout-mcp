"""Tests for performance analyzer module."""

from webscout_mcp.performance_analyzer import PerformanceAnalyzer, PerformanceMetrics, analyze_performance


class TestPerformanceMetrics:
    """Test PerformanceMetrics class."""

    def test_metrics_creation(self):
        metrics = PerformanceMetrics()
        assert metrics.html_size_bytes == 0
        assert metrics.overall_score == 0.0
        assert metrics.issues == []
        assert metrics.recommendations == []

    def test_metrics_to_dict(self):
        metrics = PerformanceMetrics(
            url="https://example.com",
            html_size_kb=50.5,
            overall_score=75.5,
            issues=["test issue"],
        )
        data = metrics.to_dict()
        assert data["url"] == "https://example.com"
        assert data["html_size_kb"] == 50.5
        assert data["overall_score"] == 75.5
        assert data["issues"] == ["test issue"]


class TestPerformanceAnalyzer:
    """Test PerformanceAnalyzer class."""

    def test_analyzer_creation(self):
        analyzer = PerformanceAnalyzer()
        assert analyzer is not None

    def test_analyze_empty_html(self):
        analyzer = PerformanceAnalyzer()
        metrics = analyzer.analyze("")
        assert len(metrics.issues) > 0
        assert "HTML" in metrics.issues[0]

    def test_analyze_basic_page(self):
        analyzer = PerformanceAnalyzer()
        html = """
        <html>
        <head>
        <title>Test Page</title>
        <link rel="stylesheet" href="style.css">
        <script src="app.js"></script>
        </head>
        <body>
        <h1>Hello</h1>
        <p>World</p>
        <img src="image1.jpg" alt="Image 1">
        <img src="image2.jpg" alt="Image 2" loading="lazy">
        </body>
        </html>
        """
        metrics = analyzer.analyze(html, url="https://example.com")
        assert metrics.url == "https://example.com"
        assert metrics.html_size_bytes > 0
        assert metrics.html_size_kb > 0
        assert metrics.dom_node_count > 0
        assert metrics.css_count == 1
        assert metrics.js_count == 1
        assert metrics.image_count == 2
        assert metrics.has_lazy_loading is True
        assert metrics.overall_score > 0

    def test_html_size_analysis(self):
        analyzer = PerformanceAnalyzer()
        # Small HTML
        small_html = "<html><body><p>Small</p></body></html>"
        metrics = analyzer.analyze(small_html)
        assert metrics.html_size_kb < 1
        assert metrics.html_size_score == 100

    def test_dom_size_analysis(self):
        analyzer = PerformanceAnalyzer()
        # Simple DOM
        html = "<html><body><div><p>Test</p></div></body></html>"
        metrics = analyzer.analyze(html)
        assert metrics.dom_node_count > 0
        assert metrics.dom_node_count < 100

    def test_resource_count_analysis(self):
        analyzer = PerformanceAnalyzer()
        html = """
        <html><head>
        <link rel="stylesheet" href="1.css">
        <link rel="stylesheet" href="2.css">
        <script src="1.js"></script>
        <script src="2.js"></script>
        <script src="3.js"></script>
        </head><body>
        <img src="1.jpg">
        <img src="2.jpg">
        <img src="3.jpg">
        <iframe src="frame.html"></iframe>
        </body></html>
        """
        metrics = analyzer.analyze(html)
        assert metrics.css_count == 2
        assert metrics.js_count == 3
        assert metrics.image_count == 3
        assert metrics.iframe_count == 1
        assert metrics.request_count >= 9

    def test_inline_css_js_detection(self):
        analyzer = PerformanceAnalyzer()
        html = """
        <html><head>
        <style>body { color: red; }</style>
        <script>console.log('test');</script>
        </head><body></body></html>
        """
        metrics = analyzer.analyze(html)
        assert metrics.has_inline_css is True
        assert metrics.has_inline_js is True

    def test_render_blocking_detection(self):
        analyzer = PerformanceAnalyzer()
        html = """
        <html><head>
        <link rel="stylesheet" href="style.css">
        <script src="app.js"></script>
        </head><body></body></html>
        """
        metrics = analyzer.analyze(html)
        assert metrics.has_render_blocking_resources is True

    def test_optimization_techniques(self):
        analyzer = PerformanceAnalyzer()
        html = """
        <html><head>
        <link rel="preconnect" href="https://cdn.example.com">
        <link rel="preload" href="font.woff2" as="font">
        </head><body>
        <img src="image.jpg" loading="lazy">
        </body></html>
        """
        metrics = analyzer.analyze(html)
        assert metrics.has_preconnect is True
        assert metrics.has_preload is True
        assert metrics.has_lazy_loading is True

    def test_response_headers_analysis(self):
        analyzer = PerformanceAnalyzer()
        html = "<html><body>Test</body></html>"
        headers = {
            "Content-Encoding": "gzip",
            "Cache-Control": "max-age=3600",
            "ETag": '"abc123"',
        }
        metrics = analyzer.analyze(html, response_headers=headers)
        assert metrics.has_gzip is True
        assert metrics.has_cache_headers is True

    def test_brotli_compression(self):
        analyzer = PerformanceAnalyzer()
        html = "<html><body>Test</body></html>"
        headers = {"Content-Encoding": "br"}
        metrics = analyzer.analyze(html, response_headers=headers)
        assert metrics.has_brotli is True

    def test_scores_calculation(self):
        analyzer = PerformanceAnalyzer()
        # Well-optimized page
        html = """
        <html><head>
        <title>Test</title>
        </head><body>
        <h1>Hello</h1>
        <p>World</p>
        <img src="img.jpg" loading="lazy">
        </body></html>
        """
        headers = {
            "Content-Encoding": "gzip",
            "Cache-Control": "max-age=3600",
        }
        metrics = analyzer.analyze(html, response_headers=headers)
        assert 0 <= metrics.html_size_score <= 100
        assert 0 <= metrics.dom_size_score <= 100
        assert 0 <= metrics.request_count_score <= 100
        assert 0 <= metrics.resource_optimization_score <= 100
        assert 0 <= metrics.caching_score <= 100
        assert 0 <= metrics.overall_score <= 100
        assert metrics.caching_score == 100
        assert metrics.has_gzip is True

    def test_issues_and_recommendations(self):
        analyzer = PerformanceAnalyzer()
        # Page with many issues
        large_html = "<html><body>" + "<div>" * 2000 + "</div>" * 2000 + "</body></html>"
        metrics = analyzer.analyze(large_html)
        assert len(metrics.issues) > 0 or len(metrics.warnings) > 0
        assert len(metrics.recommendations) > 0


class TestConvenienceFunction:
    """Test analyze_performance convenience function."""

    def test_analyze_performance(self):
        html = "<html><body><p>Test</p></body></html>"
        metrics = analyze_performance(html, url="https://example.com")
        assert isinstance(metrics, PerformanceMetrics)
        assert metrics.url == "https://example.com"
        assert metrics.html_size_bytes > 0
