"""Tests for content extractor module."""

import pytest

from webscout_mcp.content_extractor import (
    ContentExtractor,
    ContentQualityAssessor,
    ExtractedContent,
    MultiAlgorithmExtractor,
    extract_content,
)

# Sample HTML for testing
SAMPLE_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>Test Article - Python Programming</title>
    <meta name="author" content="Test Author">
    <meta name="date" content="2024-01-15">
</head>
<body>
    <header>
        <nav>Navigation links here</nav>
    </header>
    <article>
        <h1>Python Programming Tutorial</h1>
        <p>Python is a popular programming language known for its simplicity and readability.</p>
        <p>It is widely used in web development, data science, artificial intelligence, and many other fields.</p>
        <p>This tutorial will cover the basics of Python programming, including variables, data types, control structures, and functions.</p>
        <p>By the end of this tutorial, you will have a solid understanding of Python fundamentals and be ready to build your own applications.</p>
        <h2>Getting Started</h2>
        <p>To get started with Python, you need to install it on your computer. You can download Python from the official website.</p>
        <p>Once installed, you can run Python scripts using the python command in your terminal or command prompt.</p>
    </article>
    <footer>
        <p>Copyright 2024 Test Author. All rights reserved.</p>
        <p>Privacy Policy | Terms of Service</p>
    </footer>
</body>
</html>
"""

SHORT_HTML = """
<html><body><p>Short content</p></body></html>
"""


class TestExtractedContent:
    """Test ExtractedContent class."""

    def test_creation(self):
        content = ExtractedContent(title="Test", content="Test content")
        assert content.title == "Test"
        assert content.content == "Test content"
        assert content.confidence == 0.0

    def test_to_dict(self):
        content = ExtractedContent(
            title="Test",
            content="Test content",
            quality_score=0.85,
            confidence=0.9,
            word_count=100,
        )
        data = content.to_dict()
        assert data["title"] == "Test"
        assert data["quality_score"] == 0.85
        assert data["word_count"] == 100


class TestContentQualityAssessor:
    """Test ContentQualityAssessor class."""

    def test_creation(self):
        assessor = ContentQualityAssessor()
        assert assessor is not None

    def test_assess_quality_good(self):
        assessor = ContentQualityAssessor()
        content = "This is a well-written article with multiple paragraphs. " * 20
        content += "\n\nSecond paragraph with good content. " * 10
        score, details = assessor.assess_quality(content, "Test Article")
        assert 0 <= score <= 1
        assert "length" in details
        assert "structure" in details
        assert "readability" in details

    def test_assess_quality_short(self):
        assessor = ContentQualityAssessor()
        score, details = assessor.assess_quality("Short", "Test")
        assert score <= 0.6  # Short content should have lower score

    def test_calculate_readability(self):
        assessor = ContentQualityAssessor()
        # Simple, readable text
        score = assessor._calculate_readability("The cat sat on the mat. It was a sunny day.")
        assert 0 <= score <= 1
        assert score > 0.5  # Should be readable

    def test_calculate_readability_empty(self):
        assessor = ContentQualityAssessor()
        assert assessor._calculate_readability("") == 0.0

    def test_detect_language_english(self):
        assessor = ContentQualityAssessor()
        assert assessor.detect_language("This is an English text.") == "en"

    def test_detect_language_chinese(self):
        assessor = ContentQualityAssessor()
        assert assessor.detect_language("这是一段中文文本，用于测试语言检测功能。") == "zh"

    def test_detect_language_japanese(self):
        assessor = ContentQualityAssessor()
        assert assessor.detect_language("これは日本語のテキストです。これは日本語のテキストです。") == "ja"

    def test_detect_language_empty(self):
        assessor = ContentQualityAssessor()
        assert assessor.detect_language("") == "unknown"


class TestMultiAlgorithmExtractor:
    """Test MultiAlgorithmExtractor class."""

    def test_creation(self):
        extractor = MultiAlgorithmExtractor(algorithms=["trafilatura", "readability"])
        assert extractor.algorithms == ["trafilatura", "readability"]

    def test_extract_sample_html(self):
        extractor = MultiAlgorithmExtractor()
        result = extractor.extract(SAMPLE_HTML, url="https://example.com/article")
        assert result is not None
        assert len(result.content) > 0
        assert result.word_count > 0
        assert result.quality_score > 0

    def test_extract_short_html(self):
        extractor = MultiAlgorithmExtractor()
        result = extractor.extract(SHORT_HTML)
        assert result is not None
        assert "Short content" in result.content

    def test_extract_empty_html(self):
        extractor = MultiAlgorithmExtractor()
        result = extractor.extract("")
        assert result.content == ""
        assert result.confidence == 0.0

    def test_simple_extract(self):
        extractor = MultiAlgorithmExtractor()
        html = "<html><body><p>Hello <b>World</b></p></body></html>"
        content = extractor._simple_extract(html)
        assert "Hello" in content
        assert "World" in content
        assert "<" not in content  # No HTML tags

    def test_post_process(self):
        extractor = MultiAlgorithmExtractor()
        result = ExtractedContent(content="  Hello   World  \n\n\n\nTest  ")
        processed = extractor._post_process(result)
        assert "Hello" in processed.content
        assert "World" in processed.content
        assert "Test" in processed.content
        assert "\n\n\n\n" not in processed.content  # Excessive newlines removed
        assert processed.word_count > 0
        assert processed.language != "unknown"


class TestContentExtractor:
    """Test ContentExtractor class."""

    def test_creation(self):
        extractor = ContentExtractor(min_quality=0.3)
        assert extractor.min_quality == 0.3

    def test_extract(self):
        extractor = ContentExtractor()
        result = extractor.extract(SAMPLE_HTML, url="https://example.com")
        assert result is not None
        assert len(result.content) > 0
        assert result.quality_score > 0

    def test_extract_batch(self):
        extractor = ContentExtractor()
        pages = [
            {"html": SAMPLE_HTML, "url": "https://example.com/1"},
            {"html": SHORT_HTML, "url": "https://example.com/2"},
        ]
        results = extractor.extract_batch(pages)
        assert len(results) == 2
        assert all(r is not None for r in results)


class TestConvenienceFunction:
    """Test extract_content convenience function."""

    def test_extract_content(self):
        result = extract_content(SAMPLE_HTML, url="https://example.com")
        assert isinstance(result, ExtractedContent)
        assert len(result.content) > 0
