"""Tests for SEO analyzer module."""

from webscout_mcp.seo_analyzer import SEOAnalyzer, SEOMetrics, analyze_seo


class TestSEOMetrics:
    """Test SEOMetrics class."""

    def test_metrics_creation(self):
        metrics = SEOMetrics()
        assert metrics.title == ""
        assert metrics.overall_score == 0.0
        assert metrics.issues == []
        assert metrics.recommendations == []

    def test_metrics_to_dict(self):
        metrics = SEOMetrics(
            title="Test Title",
            overall_score=75.5,
            issues=["test issue"],
            recommendations=["test recommendation"],
        )
        data = metrics.to_dict()
        assert data["title"] == "Test Title"
        assert data["overall_score"] == 75.5
        assert data["issues"] == ["test issue"]


class TestSEOAnalyzer:
    """Test SEOAnalyzer class."""

    def test_analyzer_creation(self):
        analyzer = SEOAnalyzer()
        assert analyzer is not None

    def test_analyze_empty_html(self):
        analyzer = SEOAnalyzer()
        metrics = analyzer.analyze("")
        assert len(metrics.issues) > 0
        assert "HTML" in metrics.issues[0]

    def test_analyze_basic_page(self):
        analyzer = SEOAnalyzer()
        html = """
        <html>
        <head>
        <title>Test Page Title for SEO Analysis</title>
        <meta name="description" content="This is a test meta description for SEO analysis purposes.">
        <link rel="canonical" href="https://example.com/test">
        </head>
        <body>
        <h1>Main Heading</h1>
        <h2>Sub Heading</h2>
        <p>This is test content with enough words to be considered good content for SEO analysis purposes.</p>
        <img src="test.jpg" alt="Test image">
        <a href="/internal">Internal link</a>
        <a href="https://external.com">External link</a>
        </body>
        </html>
        """
        metrics = analyzer.analyze(html, url="https://example.com/test")
        assert metrics.title == "Test Page Title for SEO Analysis"
        assert metrics.title_length > 0
        assert metrics.meta_description != ""
        assert metrics.has_canonical is True
        assert metrics.h1_count == 1
        assert metrics.h2_count == 1
        assert metrics.total_images == 1
        assert metrics.images_with_alt == 1
        assert metrics.total_links == 2
        assert metrics.internal_links >= 1
        assert metrics.external_links >= 1
        assert metrics.overall_score > 0

    def test_meta_tag_analysis(self):
        analyzer = SEOAnalyzer()
        html = """
        <html><head>
        <title>Perfect Title Length for SEO</title>
        <meta name="description" content="This is a perfect meta description that is exactly the right length for SEO.">
        <meta name="keywords" content="seo, test, analysis">
        <meta name="robots" content="index, follow">
        </head><body></body></html>
        """
        metrics = analyzer.analyze(html)
        assert metrics.title != ""
        assert metrics.meta_description != ""
        assert len(metrics.meta_keywords) == 3
        assert metrics.robots_meta == "index, follow"

    def test_heading_analysis(self):
        analyzer = SEOAnalyzer()
        html = """
        <html><body>
        <h1>Main</h1>
        <h2>Sub1</h2><h2>Sub2</h2>
        <h3>Subsub1</h3>
        <h4>Subsubsub</h4>
        </body></html>
        """
        metrics = analyzer.analyze(html)
        assert metrics.h1_count == 1
        assert metrics.h2_count == 2
        assert metrics.h3_count == 1
        assert metrics.h4_count == 1

    def test_image_analysis(self):
        analyzer = SEOAnalyzer()
        html = """
        <html><body>
        <img src="img1.jpg" alt="Image with alt">
        <img src="img2.jpg">
        <img src="img3.jpg" alt="Another image">
        </body></html>
        """
        metrics = analyzer.analyze(html)
        assert metrics.total_images == 3
        assert metrics.images_with_alt == 2
        assert metrics.images_without_alt == 1
        assert metrics.image_alt_coverage > 0

    def test_link_analysis(self):
        analyzer = SEOAnalyzer()
        html = """
        <html><body>
        <a href="/internal1">Internal 1</a>
        <a href="/internal2">Internal 2</a>
        <a href="https://external.com">External</a>
        <a href="https://example.com/page">Same domain</a>
        </body></html>
        """
        metrics = analyzer.analyze(html, url="https://example.com/page")
        assert metrics.total_links == 4
        assert metrics.internal_links >= 2
        assert metrics.external_links >= 1

    def test_url_analysis(self):
        analyzer = SEOAnalyzer()
        # Short URL with hyphens
        metrics = analyzer.analyze("<html></html>", url="https://example.com/short-url-with-hyphens")
        assert metrics.url_length > 0
        assert metrics.url_has_hyphens is True

    def test_content_analysis(self):
        analyzer = SEOAnalyzer()
        long_text = " ".join(["word" for _ in range(500)])
        html = f"<html><body><p>{long_text}</p></body></html>"
        metrics = analyzer.analyze(html)
        assert metrics.word_count >= 300
        assert metrics.content_ok is True

    def test_social_tags_analysis(self):
        analyzer = SEOAnalyzer()
        html = """
        <html><head>
        <meta property="og:title" content="OG Title">
        <meta property="og:description" content="OG Description">
        <meta property="og:image" content="https://example.com/image.jpg">
        <meta name="twitter:card" content="summary_large_image">
        <meta name="twitter:title" content="Twitter Title">
        </head><body></body></html>
        """
        metrics = analyzer.analyze(html)
        assert metrics.has_og_tags is True
        assert metrics.og_title == "OG Title"
        assert metrics.has_twitter_cards is True
        assert metrics.twitter_card == "summary_large_image"

    def test_schema_analysis(self):
        analyzer = SEOAnalyzer()
        html = """
        <html><head>
        <script type="application/ld+json">
        {"@context": "https://schema.org", "@type": "Article", "headline": "Test"}
        </script>
        </head><body></body></html>
        """
        metrics = analyzer.analyze(html)
        assert metrics.has_schema_markup is True
        assert "Article" in metrics.schema_types

    def test_scores_calculation(self):
        analyzer = SEOAnalyzer()
        html = """
        <html><head>
        <title>Good Title for SEO Analysis Test Page</title>
        <meta name="description" content="This is a good meta description for SEO analysis testing purposes.">
        <link rel="canonical" href="https://example.com/test">
        <meta property="og:title" content="OG Title">
        <script type="application/ld+json">{"@type": "WebPage"}</script>
        </head><body>
        <h1>Main Heading</h1><h2>Sub</h2>
        <p>{"word " * 400}</p>
        <img src="test.jpg" alt="Test">
        <a href="/link">Link</a>
        </body></html>
        """
        metrics = analyzer.analyze(html, url="https://example.com/test-page")
        assert 0 <= metrics.meta_score <= 100
        assert 0 <= metrics.heading_score <= 100
        assert 0 <= metrics.image_score <= 100
        assert 0 <= metrics.link_score <= 100
        assert 0 <= metrics.url_score <= 100
        assert 0 <= metrics.content_score <= 100
        assert 0 <= metrics.social_score <= 100
        assert 0 <= metrics.schema_score <= 100
        assert 0 <= metrics.overall_score <= 100

    def test_issues_and_recommendations(self):
        analyzer = SEOAnalyzer()
        # Page with many issues
        html = """
        <html><head><title>Short</title></head>
        <body><p>Short content.</p>
        <img src="noalt.jpg">
        </body></html>
        """
        metrics = analyzer.analyze(html)
        assert len(metrics.issues) > 0
        assert len(metrics.recommendations) > 0


class TestConvenienceFunction:
    """Test analyze_seo convenience function."""

    def test_analyze_seo(self):
        html = "<html><head><title>Test</title></head><body><p>Test content</p></body></html>"
        metrics = analyze_seo(html, url="https://example.com")
        assert isinstance(metrics, SEOMetrics)
        assert metrics.title == "Test"
