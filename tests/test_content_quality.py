"""Tests for content quality assessment module."""

import pytest

from webscout_mcp.content_quality import (
    ContentQualityAnalyzer,
    ContentQualityMetrics,
    analyze_content_quality,
)


class TestContentQualityMetrics:
    """Test ContentQualityMetrics class."""

    def test_metrics_creation(self):
        metrics = ContentQualityMetrics()
        assert metrics.word_count == 0
        assert metrics.char_count == 0
        assert metrics.sentence_count == 0
        assert metrics.overall_score == 0.0
        assert metrics.issues == []
        assert metrics.suggestions == []

    def test_metrics_to_dict(self):
        metrics = ContentQualityMetrics(
            word_count=100,
            overall_score=75.5,
            issues=["test issue"],
            suggestions=["test suggestion"],
        )
        data = metrics.to_dict()
        assert data["word_count"] == 100
        assert data["overall_score"] == 75.5
        assert data["issues"] == ["test issue"]
        assert data["suggestions"] == ["test suggestion"]


class TestContentQualityAnalyzer:
    """Test ContentQualityAnalyzer class."""

    def test_analyzer_creation(self):
        analyzer = ContentQualityAnalyzer()
        assert analyzer is not None

    def test_analyze_empty_content(self):
        analyzer = ContentQualityAnalyzer()
        metrics = analyzer.analyze("")
        assert metrics.word_count == 0
        assert len(metrics.issues) > 0
        assert "empty" in metrics.issues[0].lower()

    def test_analyze_short_content(self):
        analyzer = ContentQualityAnalyzer()
        text = "Short text."
        metrics = analyzer.analyze(text)
        assert metrics.word_count > 0
        assert metrics.char_count > 0
        assert metrics.content_depth_score <= 40  # Short content should have low depth score

    def test_analyze_medium_content(self):
        analyzer = ContentQualityAnalyzer()
        text = """
        This is a medium-length article about web scraping.
        Web scraping is the process of extracting data from websites.
        It can be done using various tools and libraries.
        Python is a popular language for web scraping due to its simplicity.
        Libraries like BeautifulSoup, Scrapy, and Playwright make web scraping easy.
        However, it is important to respect websites' terms of service and robots.txt.
        Always be polite and do not overload servers with too many requests.
        """
        metrics = analyzer.analyze(text)
        assert metrics.word_count > 50
        assert metrics.sentence_count > 5
        assert metrics.readability_score > 0
        assert metrics.overall_score > 0

    def test_analyze_long_content(self):
        analyzer = ContentQualityAnalyzer()
        # Generate a longer text
        text = " ".join(
            [
                f"This is sentence number {i} about content quality analysis. "
                f"Quality analysis helps improve readability and SEO. "
                f"Good content should be clear, concise, and well-structured."
                for i in range(50)
            ]
        )
        metrics = analyzer.analyze(text)
        assert metrics.word_count > 300
        assert metrics.content_depth_score >= 60

    def test_basic_metrics_calculation(self):
        analyzer = ContentQualityAnalyzer()
        text = "Hello world. This is a test. How are you?"
        metrics = analyzer.analyze(text)
        assert metrics.word_count >= 8
        assert metrics.sentence_count == 3
        assert metrics.char_count > 0

    def test_readability_scores(self):
        analyzer = ContentQualityAnalyzer()
        # Simple text should have high readability
        simple_text = "The cat sat on the mat. It was a sunny day. The dog ran fast."
        metrics = analyzer.analyze(simple_text)
        assert metrics.flesch_reading_ease > 0
        assert metrics.flesch_reading_ease <= 100

    def test_keyword_analysis(self):
        analyzer = ContentQualityAnalyzer()
        text = """
        Python programming language. Python is great for data science.
        Python web development. Python automation scripts.
        """
        metrics = analyzer.analyze(text)
        assert metrics.unique_keywords > 0
        assert len(metrics.keyword_density) > 0
        # "python" should be a top keyword
        assert "python" in metrics.keyword_density

    def test_structure_analysis_with_html(self):
        analyzer = ContentQualityAnalyzer()
        html = """
        <html>
        <head><title>Test Page</title>
        <meta name="description" content="Test description"></head>
        <body>
        <h1>Main Heading</h1>
        <h2>Sub Heading</h2>
        <ul><li>Item 1</li><li>Item 2</li></ul>
        <a href="https://example.com">Link</a>
        <img src="test.jpg" alt="Test">
        <p>Test content here.</p>
        </body>
        </html>
        """
        text = "Test content here. This is a test page with structure."
        metrics = analyzer.analyze(text, html=html)
        assert metrics.heading_count >= 2
        assert metrics.list_count >= 1
        assert metrics.link_count >= 1
        assert metrics.image_count >= 1
        assert metrics.has_title is True
        assert metrics.has_meta_description is True

    def test_quality_scores(self):
        analyzer = ContentQualityAnalyzer()
        text = """
        This is a well-written article about content quality.
        Quality content is essential for user engagement.
        Good articles have clear structure and readability.
        They include headings, lists, and relevant images.
        SEO optimization helps content reach more readers.
        """
        html = """
        <html><head><title>Quality Article</title>
        <meta name="description" content="About content quality"></head>
        <body><h1>Quality</h1><p>Content here.</p></body></html>
        """
        metrics = analyzer.analyze(text, html=html)
        assert 0 <= metrics.readability_score <= 100
        assert 0 <= metrics.structure_score <= 100
        assert 0 <= metrics.seo_score <= 100
        assert 0 <= metrics.content_depth_score <= 100
        assert 0 <= metrics.overall_score <= 100

    def test_issues_and_suggestions(self):
        analyzer = ContentQualityAnalyzer()
        # Short content without structure should generate issues
        text = "Short."
        metrics = analyzer.analyze(text)
        assert len(metrics.issues) > 0
        assert len(metrics.suggestions) > 0

    def test_chinese_content(self):
        analyzer = ContentQualityAnalyzer()
        text = """
        这是一篇关于内容质量分析的中文文章。
        内容质量分析有助于提高可读性和搜索引擎优化。
        好的内容应该清晰、简洁、结构良好。
        文章应该包含标题、列表和相关图片。
        """
        metrics = analyzer.analyze(text)
        assert metrics.word_count > 0
        assert metrics.char_count > 0
        assert metrics.overall_score > 0

    def test_stop_words_filtering(self):
        analyzer = ContentQualityAnalyzer()
        text = "The quick brown fox jumps over the lazy dog. The dog was very lazy."
        metrics = analyzer.analyze(text)
        # "the" should not be in keyword density (it's a stop word)
        assert "the" not in metrics.keyword_density


class TestConvenienceFunction:
    """Test analyze_content_quality convenience function."""

    def test_analyze_content_quality(self):
        text = "This is a test of the convenience function."
        metrics = analyze_content_quality(text)
        assert isinstance(metrics, ContentQualityMetrics)
        assert metrics.word_count > 0

    def test_analyze_with_html_and_metadata(self):
        text = "Test content"
        html = "<html><head><title>Test</title></head><body><p>Test</p></body></html>"
        metadata = {"title": "Test", "description": "Test description"}
        metrics = analyze_content_quality(text, html=html, metadata=metadata)
        assert metrics.has_title is True
        assert metrics.has_meta_description is True
