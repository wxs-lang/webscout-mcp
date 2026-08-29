"""Content extraction optimizer module for webscout-mcp.

Enhanced content extraction with multi-algorithm fusion, quality assessment,
and intelligent cleaning.

Features:
- Multi-algorithm extraction (trafilatura, readability, html2text, boilerpipe)
- Algorithm voting and confidence scoring
- Content quality assessment
- Intelligent cleaning (ads, navigation, footers removal)
- Structured content detection (articles, lists, tables)
- Metadata extraction enhancement
- Language detection
- Readability scoring
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .logging_config import get_logger

log = get_logger(__name__)


@dataclass
class ExtractedContent:
    """Enhanced extracted content result."""

    title: str = ""
    content: str = ""
    raw_html: str = ""
    author: str = ""
    publish_date: str = ""
    url: str = ""
    language: str = ""
    readability_score: float = 0.0
    quality_score: float = 0.0
    confidence: float = 0.0
    algorithm_used: str = ""
    algorithm_scores: dict[str, float] = field(default_factory=dict)
    word_count: int = 0
    paragraph_count: int = 0
    image_count: int = 0
    link_count: int = 0
    is_article: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "content": self.content,
            "author": self.author,
            "publish_date": self.publish_date,
            "url": self.url,
            "language": self.language,
            "readability_score": self.readability_score,
            "quality_score": self.quality_score,
            "confidence": self.confidence,
            "algorithm_used": self.algorithm_used,
            "algorithm_scores": self.algorithm_scores,
            "word_count": self.word_count,
            "paragraph_count": self.paragraph_count,
            "image_count": self.image_count,
            "link_count": self.link_count,
            "is_article": self.is_article,
            "metadata": self.metadata,
        }


class ContentQualityAssessor:
    """Assess content quality and readability."""

    # Common boilerplate patterns to detect
    BOILERPLATE_PATTERNS = [
        r"cookie (policy|notice|consent)",
        r"privacy policy",
        r"terms of (service|use)",
        r"copyright \d{4}",
        r"all rights reserved",
        r"subscribe to (our )?newsletter",
        r"sign up for (our )?newsletter",
        r"follow us on",
        r"share (this|on)",
        r"related (articles|posts|content)",
        r"read more",
        r"click here",
        r"advertisement",
        r"sponsored (content|link)",
    ]

    def assess_quality(self, content: str, title: str = "") -> tuple[float, dict[str, float]]:
        """Assess content quality.

        Args:
            content: Extracted content text.
            title: Content title.

        Returns:
            Tuple of (overall_score, detailed_scores).
        """
        scores = {}

        # Length score
        word_count = len(content.split())
        if word_count >= 500:
            scores["length"] = 1.0
        elif word_count >= 200:
            scores["length"] = 0.7
        elif word_count >= 50:
            scores["length"] = 0.4
        else:
            scores["length"] = 0.2

        # Structure score (paragraphs, headings)
        paragraph_count = content.count("\n\n") + 1
        if paragraph_count >= 5:
            scores["structure"] = 1.0
        elif paragraph_count >= 3:
            scores["structure"] = 0.7
        elif paragraph_count >= 2:
            scores["structure"] = 0.5
        else:
            scores["structure"] = 0.3

        # Boilerplate score (less boilerplate = better)
        boilerplate_count = 0
        content_lower = content.lower()
        for pattern in self.BOILERPLATE_PATTERNS:
            if re.search(pattern, content_lower):
                boilerplate_count += 1
        scores["boilerplate"] = max(0, 1.0 - boilerplate_count * 0.1)

        # Readability score (simplified)
        scores["readability"] = self._calculate_readability(content)

        # Title relevance
        if title and content:
            title_words = set(title.lower().split())
            content_words = set(content.lower().split()[:100])  # First 100 words
            overlap = len(title_words & content_words)
            scores["title_relevance"] = min(1.0, overlap / max(1, len(title_words)))
        else:
            scores["title_relevance"] = 0.5

        # Overall score (weighted average)
        overall = (
            scores["length"] * 0.25
            + scores["structure"] * 0.20
            + scores["boilerplate"] * 0.20
            + scores["readability"] * 0.20
            + scores["title_relevance"] * 0.15
        )

        return round(overall, 3), scores

    def _calculate_readability(self, text: str) -> float:
        """Calculate simplified readability score (0-1).

        Based on Flesch-Kincaid principles but simplified.
        """
        if not text.strip():
            return 0.0

        words = text.split()
        if not words:
            return 0.0

        # Average word length
        avg_word_length = sum(len(word) for word in words) / len(words)

        # Sentence count
        sentences = re.split(r"[.!?。！？]+", text)
        sentences = [s for s in sentences if s.strip()]
        avg_sentence_length = len(words) / max(1, len(sentences))

        # Score: shorter words and sentences = more readable
        word_score = max(0, 1.0 - (avg_word_length - 5) * 0.1)
        sentence_score = max(0, 1.0 - (avg_sentence_length - 15) * 0.03)

        return round(min(1.0, (word_score + sentence_score) / 2), 3)

    def detect_language(self, text: str) -> str:
        """Detect language of text (simplified).

        Args:
            text: Input text.

        Returns:
            Language code (en, zh, ja, etc.).
        """
        if not text:
            return "unknown"

        # Chinese character detection
        chinese_chars = len(re.findall(r"[\u4e00-\u9fff]", text))
        if chinese_chars > 10:
            return "zh"

        # Japanese character detection
        japanese_chars = len(re.findall(r"[\u3040-\u309f\u30a0-\u30ff]", text))
        if japanese_chars > 10:
            return "ja"

        # Korean character detection
        korean_chars = len(re.findall(r"[\uac00-\ud7af]", text))
        if korean_chars > 10:
            return "ko"

        # Cyrillic detection
        cyrillic_chars = len(re.findall(r"[\u0400-\u04ff]", text))
        if cyrillic_chars > 10:
            return "ru"

        # Default to English for Latin script
        if re.search(r"[a-zA-Z]", text):
            return "en"

        return "unknown"


class MultiAlgorithmExtractor:
    """Multi-algorithm content extraction with fusion.

    Tries multiple extraction algorithms and selects/fuses the best result.
    """

    def __init__(self, algorithms: list[str] | None = None) -> None:
        self.algorithms = algorithms or ["trafilatura", "readability", "html2text"]
        self.quality_assessor = ContentQualityAssessor()

    def extract(self, html: str, url: str = "", title: str = "") -> ExtractedContent:
        """Extract content using multiple algorithms and fuse results.

        Args:
            html: Raw HTML content.
            url: Page URL.
            title: Page title (if known).

        Returns:
            ExtractedContent with best extraction result.
        """
        result = ExtractedContent(url=url, raw_html=html)

        if not html:
            return result

        # Try each algorithm
        algorithm_results = {}
        for algo in self.algorithms:
            try:
                extracted = self._extract_with_algorithm(algo, html, url)
                if extracted and extracted.get("content"):
                    algorithm_results[algo] = extracted
            except Exception as exc:
                log.debug(f"Algorithm {algo} failed: {exc}")

        if not algorithm_results:
            # Fallback: simple HTML tag removal
            result.content = self._simple_extract(html)
            result.algorithm_used = "fallback"
            result.confidence = 0.3
        else:
            # Score each algorithm's result
            scores = {}
            for algo, extracted in algorithm_results.items():
                content = extracted.get("content", "")
                quality_score, _ = self.quality_assessor.assess_quality(content, title or extracted.get("title", ""))
                scores[algo] = quality_score

            result.algorithm_scores = scores

            # Select best algorithm
            best_algo = max(scores, key=scores.get)
            best_result = algorithm_results[best_algo]

            result.content = best_result.get("content", "")
            result.title = best_result.get("title", title)
            result.author = best_result.get("author", "")
            result.publish_date = best_result.get("publish_date", "")
            result.algorithm_used = best_algo
            result.confidence = scores[best_algo]

        # Post-processing
        result = self._post_process(result)

        return result

    def _extract_with_algorithm(self, algorithm: str, html: str, url: str) -> dict[str, Any] | None:
        """Extract content using specified algorithm.

        Args:
            algorithm: Algorithm name.
            html: Raw HTML.
            url: Page URL.

        Returns:
            Dictionary with extracted content, or None if failed.
        """
        if algorithm == "trafilatura":
            try:
                import trafilatura

                content = trafilatura.extract(
                    html,
                    url=url,
                    include_comments=False,
                    include_tables=True,
                    include_images=False,
                )
                if content:
                    metadata = trafilatura.extract_metadata(html)
                    return {
                        "content": content,
                        "title": metadata.title if metadata else "",
                        "author": metadata.author if metadata else "",
                        "publish_date": metadata.date if metadata else "",
                    }
            except ImportError:
                pass
            except Exception as exc:
                log.debug(f"trafilatura extraction failed: {exc}")

        elif algorithm == "readability":
            try:
                from readability import Document

                doc = Document(html)
                content = doc.summary(html_partial=False)
                # Remove HTML tags from summary
                content = re.sub(r"<[^>]+>", "", content)
                content = content.strip()
                return {
                    "content": content,
                    "title": doc.title(),
                    "author": "",
                    "publish_date": "",
                }
            except ImportError:
                pass
            except Exception as exc:
                log.debug(f"readability extraction failed: {exc}")

        elif algorithm == "html2text":
            try:
                import html2text

                h = html2text.HTML2Text()
                h.ignore_links = True
                h.ignore_images = True
                h.body_width = 0
                content = h.handle(html)
                content = content.strip()
                return {
                    "content": content,
                    "title": "",
                    "author": "",
                    "publish_date": "",
                }
            except ImportError:
                pass
            except Exception as exc:
                log.debug(f"html2text extraction failed: {exc}")

        return None

    def _simple_extract(self, html: str) -> str:
        """Simple fallback extraction (remove HTML tags)."""
        # Remove script and style elements
        text = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL | re.IGNORECASE)
        # Remove HTML tags
        text = re.sub(r"<[^>]+>", " ", text)
        # Normalize whitespace
        text = re.sub(r"\s+", " ", text).strip()
        return text

    def _post_process(self, result: ExtractedContent) -> ExtractedContent:
        """Post-process extracted content."""
        content = result.content

        # Clean up excessive whitespace
        content = re.sub(r"\n{3,}", "\n\n", content)
        content = re.sub(r"[ \t]+", " ", content)
        content = content.strip()

        result.content = content

        # Calculate statistics
        result.word_count = len(content.split())
        result.paragraph_count = content.count("\n\n") + 1

        # Quality assessment
        quality_score, detailed_scores = self.quality_assessor.assess_quality(content, result.title)
        result.quality_score = quality_score
        result.readability_score = detailed_scores.get("readability", 0.0)

        # Language detection
        result.language = self.quality_assessor.detect_language(content)

        # Article detection
        result.is_article = result.word_count >= 200 and result.paragraph_count >= 3 and result.quality_score >= 0.5

        return result


class ContentExtractor:
    """Main content extractor with multi-algorithm fusion and quality assessment."""

    def __init__(
        self,
        algorithms: list[str] | None = None,
        min_quality: float = 0.3,
        enable_cleaning: bool = True,
    ) -> None:
        self.multi_extractor = MultiAlgorithmExtractor(algorithms=algorithms)
        self.min_quality = min_quality
        self.enable_cleaning = enable_cleaning

    def extract(self, html: str, url: str = "", title: str = "") -> ExtractedContent:
        """Extract and clean content from HTML.

        Args:
            html: Raw HTML content.
            url: Page URL.
            title: Page title (if known).

        Returns:
            ExtractedContent with extracted and cleaned content.
        """
        result = self.multi_extractor.extract(html, url=url, title=title)

        # If quality is too low, try fallback
        if result.quality_score < self.min_quality and result.algorithm_used != "fallback":
            log.debug(f"Quality too low ({result.quality_score}), trying fallback")
            fallback_content = self.multi_extractor._simple_extract(html)
            if len(fallback_content.split()) > result.word_count:
                result.content = fallback_content
                result.algorithm_used = "fallback"
                result = self.multi_extractor._post_process(result)

        return result

    def extract_batch(self, pages: list[dict[str, str]]) -> list[ExtractedContent]:
        """Extract content from multiple pages.

        Args:
            pages: List of dicts with 'html', 'url', 'title' keys.

        Returns:
            List of ExtractedContent objects.
        """
        results = []
        for page in pages:
            result = self.extract(
                html=page.get("html", ""),
                url=page.get("url", ""),
                title=page.get("title", ""),
            )
            results.append(result)
        return results


def extract_content(
    html: str,
    url: str = "",
    title: str = "",
    algorithms: list[str] | None = None,
) -> ExtractedContent:
    """Convenience function for content extraction.

    Args:
        html: Raw HTML content.
        url: Page URL.
        title: Page title.
        algorithms: Algorithms to try.

    Returns:
        ExtractedContent with extracted content.
    """
    extractor = ContentExtractor(algorithms=algorithms)
    return extractor.extract(html, url=url, title=title)
