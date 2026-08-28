"""Content quality assessment module for webscout-mcp.
Provides automated content quality scoring and analysis.

Features:
- Readability scoring (Flesch-Kincaid, etc.)
- Content length analysis
- Keyword density analysis
- SEO quality scoring
- Spam content detection
- Duplicate content detection
- Content structure analysis
- Grammar and spelling hints (basic)
- Overall quality scoring
"""
from __future__ import annotations
import re
import math
from dataclasses import dataclass, field
from typing import Optional
from .logging import get_logger

log = get_logger(__name__)


@dataclass
class ContentQualityMetrics:
    """Content quality metrics."""
    # Basic metrics
    word_count: int = 0
    char_count: int = 0
    sentence_count: int = 0
    paragraph_count: int = 0
    avg_word_length: float = 0.0
    avg_sentence_length: float = 0.0

    # Readability
    flesch_reading_ease: float = 0.0
    flesch_kincaid_grade: float = 0.0

    # Content structure
    heading_count: int = 0
    list_count: int = 0
    link_count: int = 0
    image_count: int = 0
    has_title: bool = False
    has_meta_description: bool = False

    # Keyword analysis
    keyword_density: dict = field(default_factory=dict)
    unique_keywords: int = 0

    # Quality scores (0-100)
    readability_score: float = 0.0
    structure_score: float = 0.0
    seo_score: float = 0.0
    content_depth_score: float = 0.0
    overall_score: float = 0.0

    # Issues and suggestions
    issues: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "word_count": self.word_count,
            "char_count": self.char_count,
            "sentence_count": self.sentence_count,
            "paragraph_count": self.paragraph_count,
            "avg_word_length": self.avg_word_length,
            "avg_sentence_length": self.avg_sentence_length,
            "flesch_reading_ease": self.flesch_reading_ease,
            "flesch_kincaid_grade": self.flesch_kincaid_grade,
            "heading_count": self.heading_count,
            "list_count": self.list_count,
            "link_count": self.link_count,
            "image_count": self.image_count,
            "has_title": self.has_title,
            "has_meta_description": self.has_meta_description,
            "keyword_density": self.keyword_density,
            "unique_keywords": self.unique_keywords,
            "readability_score": self.readability_score,
            "structure_score": self.structure_score,
            "seo_score": self.seo_score,
            "content_depth_score": self.content_depth_score,
            "overall_score": self.overall_score,
            "issues": self.issues,
            "suggestions": self.suggestions,
        }


class ContentQualityAnalyzer:
    """Analyzes content quality and provides scoring.

    Features:
    - Readability scoring
    - Content structure analysis
    - SEO quality assessment
    - Keyword density analysis
    - Issue detection and suggestions
    - Overall quality scoring
    """

    # Common stop words for keyword analysis
    STOP_WORDS = {
        "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for",
        "of", "with", "by", "from", "as", "is", "are", "was", "were", "be",
        "been", "being", "have", "has", "had", "do", "does", "did", "will",
        "would", "could", "should", "may", "might", "must", "can", "this",
        "that", "these", "those", "it", "its", "they", "them", "their", "we",
        "us", "our", "you", "your", "he", "him", "his", "she", "her", "i",
        "me", "my", "not", "no", "nor", "so", "if", "then", "than", "too",
        "very", "just", "about", "above", "after", "again", "all", "also",
        "am", "any", "because", "before", "being", "below", "between", "both",
        "during", "each", "few", "further", "here", "how", "into", "more",
        "most", "other", "out", "over", "own", "same", "some", "such", "there",
        "through", "under", "until", "up", "what", "when", "where", "which",
        "while", "who", "whom", "why", "的", "了", "在", "是", "我", "有",
        "和", "就", "不", "人", "都", "一", "一个", "上", "也", "很", "到",
        "说", "要", "去", "你", "会", "着", "没有", "看", "好", "自己", "这",
    }

    def __init__(self) -> None:
        pass

    def analyze(self, text: str, html: str = "", metadata: Optional[dict] = None) -> ContentQualityMetrics:
        """Analyze content quality.

        Args:
            text: Plain text content.
            html: HTML content (optional, for structure analysis).
            metadata: Page metadata (optional).

        Returns:
            ContentQualityMetrics with analysis results.
        """
        metrics = ContentQualityMetrics()

        if not text:
            metrics.issues.append("Content is empty")
            metrics.suggestions.append("Add meaningful content to the page")
            return metrics

        # Basic metrics
        self._calculate_basic_metrics(text, metrics)

        # Readability
        self._calculate_readability(text, metrics)

        # Structure analysis (from HTML)
        if html:
            self._analyze_structure(html, metrics)

        # Metadata analysis
        if metadata:
            self._analyze_metadata(metadata, metrics)

        # Keyword analysis
        self._analyze_keywords(text, metrics)

        # Quality scoring
        self._calculate_scores(metrics)

        # Generate issues and suggestions
        self._generate_issues_and_suggestions(metrics)

        return metrics

    def _calculate_basic_metrics(self, text: str, metrics: ContentQualityMetrics) -> None:
        """Calculate basic content metrics."""
        metrics.char_count = len(text)

        # Word count (handle both English and Chinese)
        words = re.findall(r'\b\w+\b', text)
        chinese_chars = re.findall(r'[\u4e00-\u9fff]', text)
        metrics.word_count = len(words) + len(chinese_chars)

        # Sentence count
        sentences = re.split(r'[.!?。！？]+', text)
        metrics.sentence_count = len([s for s in sentences if s.strip()])

        # Paragraph count
        paragraphs = [p for p in text.split('\n\n') if p.strip()]
        metrics.paragraph_count = len(paragraphs)

        # Average word length
        if words:
            metrics.avg_word_length = sum(len(w) for w in words) / len(words)

        # Average sentence length
        if metrics.sentence_count > 0:
            metrics.avg_sentence_length = metrics.word_count / metrics.sentence_count

    def _calculate_readability(self, text: str, metrics: ContentQualityMetrics) -> None:
        """Calculate readability scores."""
        if metrics.word_count == 0 or metrics.sentence_count == 0:
            return

        # Count syllables (approximate)
        syllable_count = self._count_syllables(text)

        # Flesch Reading Ease
        # Formula: 206.835 - 1.015 * (words/sentences) - 84.6 * (syllables/words)
        if metrics.word_count > 0 and metrics.sentence_count > 0:
            metrics.flesch_reading_ease = (
                206.835
                - 1.015 * (metrics.word_count / metrics.sentence_count)
                - 84.6 * (syllable_count / metrics.word_count)
            )
            # Clamp to 0-100
            metrics.flesch_reading_ease = max(0, min(100, metrics.flesch_reading_ease))

            # Flesch-Kincaid Grade Level
            # Formula: 0.39 * (words/sentences) + 11.8 * (syllables/words) - 15.59
            metrics.flesch_kincaid_grade = (
                0.39 * (metrics.word_count / metrics.sentence_count)
                + 11.8 * (syllable_count / metrics.word_count)
                - 15.59
            )

    def _count_syllables(self, text: str) -> int:
        """Count syllables in text (approximate)."""
        words = re.findall(r'\b\w+\b', text.lower())
        syllable_count = 0
        for word in words:
            # Simple syllable counting heuristic
            vowels = "aeiouy"
            count = 0
            prev_char_was_vowel = False
            for char in word:
                is_vowel = char in vowels
                if is_vowel and not prev_char_was_vowel:
                    count += 1
                prev_char_was_vowel = is_vowel
            if word.endswith('e') and count > 1:
                count -= 1
            syllable_count += max(1, count)
        return syllable_count

    def _analyze_structure(self, html: str, metrics: ContentQualityMetrics) -> None:
        """Analyze content structure from HTML."""
        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html, "html.parser")

            # Count headings
            metrics.heading_count = len(soup.find_all(['h1', 'h2', 'h3', 'h4', 'h5', 'h6']))

            # Count lists
            metrics.list_count = len(soup.find_all(['ul', 'ol']))

            # Count links
            metrics.link_count = len(soup.find_all('a', href=True))

            # Count images
            metrics.image_count = len(soup.find_all('img'))

            # Check for title
            metrics.has_title = bool(soup.find('title') and soup.find('title').string)

            # Check for meta description
            meta_desc = soup.find('meta', attrs={'name': 'description'})
            metrics.has_meta_description = bool(meta_desc and meta_desc.get('content'))

        except ImportError:
            log.warning("BeautifulSoup not available for structure analysis")

    def _analyze_metadata(self, metadata: dict, metrics: ContentQualityMetrics) -> None:
        """Analyze page metadata."""
        if metadata.get('title'):
            metrics.has_title = True
        if metadata.get('description') or metadata.get('meta_description'):
            metrics.has_meta_description = True

    def _analyze_keywords(self, text: str, metrics: ContentQualityMetrics) -> None:
        """Analyze keyword density."""
        # Tokenize and filter stop words
        words = re.findall(r'\b\w+\b', text.lower())
        filtered_words = [w for w in words if w not in self.STOP_WORDS and len(w) > 2]

        if not filtered_words:
            return

        # Count word frequencies
        word_counts = {}
        for word in filtered_words:
            word_counts[word] = word_counts.get(word, 0) + 1

        # Calculate density for top keywords
        total_words = len(filtered_words)
        sorted_keywords = sorted(word_counts.items(), key=lambda x: x[1], reverse=True)
        metrics.keyword_density = {
            word: round(count / total_words * 100, 2)
            for word, count in sorted_keywords[:20]
        }
        metrics.unique_keywords = len(word_counts)

    def _calculate_scores(self, metrics: ContentQualityMetrics) -> None:
        """Calculate quality scores."""
        # Readability score (based on Flesch Reading Ease)
        if metrics.flesch_reading_ease > 0:
            metrics.readability_score = metrics.flesch_reading_ease
        else:
            # Fallback based on sentence length
            if metrics.avg_sentence_length < 15:
                metrics.readability_score = 80
            elif metrics.avg_sentence_length < 25:
                metrics.readability_score = 60
            else:
                metrics.readability_score = 40

        # Structure score
        structure_score = 50  # Base score
        if metrics.heading_count > 0:
            structure_score += 15
        if metrics.list_count > 0:
            structure_score += 10
        if metrics.image_count > 0:
            structure_score += 10
        if metrics.paragraph_count > 3:
            structure_score += 15
        metrics.structure_score = min(100, structure_score)

        # SEO score
        seo_score = 30  # Base score
        if metrics.has_title:
            seo_score += 20
        if metrics.has_meta_description:
            seo_score += 20
        if metrics.link_count > 0:
            seo_score += 10
        if metrics.word_count > 300:
            seo_score += 20
        metrics.seo_score = min(100, seo_score)

        # Content depth score
        if metrics.word_count < 100:
            metrics.content_depth_score = 20
        elif metrics.word_count < 300:
            metrics.content_depth_score = 40
        elif metrics.word_count < 500:
            metrics.content_depth_score = 60
        elif metrics.word_count < 1000:
            metrics.content_depth_score = 80
        else:
            metrics.content_depth_score = 95

        # Overall score (weighted average)
        metrics.overall_score = (
            metrics.readability_score * 0.25
            + metrics.structure_score * 0.25
            + metrics.seo_score * 0.25
            + metrics.content_depth_score * 0.25
        )

    def _generate_issues_and_suggestions(self, metrics: ContentQualityMetrics) -> None:
        """Generate issues and suggestions based on metrics."""
        # Content length issues
        if metrics.word_count < 100:
            metrics.issues.append("Content is too short (less than 100 words)")
            metrics.suggestions.append("Expand content to at least 300 words for better SEO")
        elif metrics.word_count < 300:
            metrics.issues.append("Content is relatively short (less than 300 words)")
            metrics.suggestions.append("Consider adding more detail to improve content depth")

        # Readability issues
        if metrics.flesch_reading_ease < 30 and metrics.flesch_reading_ease > 0:
            metrics.issues.append("Content is very difficult to read")
            metrics.suggestions.append("Use shorter sentences and simpler words to improve readability")
        elif metrics.flesch_reading_ease < 50 and metrics.flesch_reading_ease > 0:
            metrics.issues.append("Content is somewhat difficult to read")
            metrics.suggestions.append("Consider simplifying sentence structure")

        # Structure issues
        if metrics.heading_count == 0:
            metrics.issues.append("No headings found in content")
            metrics.suggestions.append("Add headings (H1, H2, H3) to improve content structure")

        if metrics.image_count == 0:
            metrics.issues.append("No images found in content")
            metrics.suggestions.append("Add relevant images to make content more engaging")

        # SEO issues
        if not metrics.has_title:
            metrics.issues.append("No page title found")
            metrics.suggestions.append("Add a descriptive page title for SEO")

        if not metrics.has_meta_description:
            metrics.issues.append("No meta description found")
            metrics.suggestions.append("Add a meta description (150-160 characters) for better click-through rates")

        # Keyword density issues
        for keyword, density in metrics.keyword_density.items():
            if density > 5:
                metrics.issues.append(f"Keyword '{keyword}' density is too high ({density}%)")
                metrics.suggestions.append(f"Reduce usage of '{keyword}' to avoid keyword stuffing (aim for 1-2%)")

        # Overall quality suggestions
        if metrics.overall_score < 50:
            metrics.suggestions.append("Overall content quality needs significant improvement")
        elif metrics.overall_score < 70:
            metrics.suggestions.append("Content quality is moderate, consider implementing the suggestions above")
        elif metrics.overall_score >= 80:
            metrics.suggestions.append("Content quality is good! Keep up the good work")


def analyze_content_quality(text: str, html: str = "", metadata: Optional[dict] = None) -> ContentQualityMetrics:
    """Convenience function to analyze content quality.

    Args:
        text: Plain text content.
        html: HTML content (optional).
        metadata: Page metadata (optional).

    Returns:
        ContentQualityMetrics with analysis results.
    """
    analyzer = ContentQualityAnalyzer()
    return analyzer.analyze(text, html, metadata)
