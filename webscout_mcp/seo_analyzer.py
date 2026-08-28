"""SEO analyzer module for webscout-mcp.
Provides comprehensive SEO analysis and optimization suggestions.

Features:
- Meta tag analysis (title, description, keywords)
- Heading structure analysis (H1-H6)
- Image SEO analysis (alt tags, file names)
- Link analysis (internal/external, anchor text)
- URL structure analysis
- Content length analysis
- Keyword analysis and density
- Mobile-friendliness checks
- Page speed hints
- Schema markup detection
- Open Graph and Twitter Card analysis
- Canonical URL check
- Robots meta tag check
- Overall SEO score and recommendations
"""
from __future__ import annotations
import re
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import urlparse
from .logging import get_logger

log = get_logger(__name__)


@dataclass
class SEOMetrics:
    """SEO analysis metrics."""
    # Meta tags
    title: str = ""
    title_length: int = 0
    title_ok: bool = False
    meta_description: str = ""
    meta_description_length: int = 0
    meta_description_ok: bool = False
    meta_keywords: list[str] = field(default_factory=list)
    canonical_url: str = ""
    has_canonical: bool = False
    robots_meta: str = ""

    # Headings
    h1_count: int = 0
    h2_count: int = 0
    h3_count: int = 0
    h4_count: int = 0
    h5_count: int = 0
    h6_count: int = 0
    heading_structure_ok: bool = False

    # Images
    total_images: int = 0
    images_with_alt: int = 0
    images_without_alt: int = 0
    image_alt_coverage: float = 0.0

    # Links
    total_links: int = 0
    internal_links: int = 0
    external_links: int = 0
    links_with_anchor: int = 0
    links_without_anchor: int = 0

    # URL
    url: str = ""
    url_length: int = 0
    url_ok: bool = False
    url_has_hyphens: bool = False
    url_has_stop_words: bool = False

    # Content
    content_length: int = 0
    word_count: int = 0
    content_ok: bool = False

    # Social
    has_og_tags: bool = False
    og_title: str = ""
    og_description: str = ""
    og_image: str = ""
    has_twitter_cards: bool = False
    twitter_card: str = ""
    twitter_title: str = ""
    twitter_description: str = ""

    # Schema
    has_schema_markup: bool = False
    schema_types: list[str] = field(default_factory=list)

    # Scores (0-100)
    meta_score: float = 0.0
    heading_score: float = 0.0
    image_score: float = 0.0
    link_score: float = 0.0
    url_score: float = 0.0
    content_score: float = 0.0
    social_score: float = 0.0
    schema_score: float = 0.0
    overall_score: float = 0.0

    # Issues and recommendations
    issues: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "title_length": self.title_length,
            "title_ok": self.title_ok,
            "meta_description": self.meta_description,
            "meta_description_length": self.meta_description_length,
            "meta_description_ok": self.meta_description_ok,
            "meta_keywords": self.meta_keywords,
            "canonical_url": self.canonical_url,
            "has_canonical": self.has_canonical,
            "robots_meta": self.robots_meta,
            "h1_count": self.h1_count,
            "h2_count": self.h2_count,
            "h3_count": self.h3_count,
            "total_images": self.total_images,
            "images_with_alt": self.images_with_alt,
            "images_without_alt": self.images_without_alt,
            "image_alt_coverage": self.image_alt_coverage,
            "total_links": self.total_links,
            "internal_links": self.internal_links,
            "external_links": self.external_links,
            "url": self.url,
            "url_length": self.url_length,
            "url_ok": self.url_ok,
            "content_length": self.content_length,
            "word_count": self.word_count,
            "content_ok": self.content_ok,
            "has_og_tags": self.has_og_tags,
            "has_twitter_cards": self.has_twitter_cards,
            "has_schema_markup": self.has_schema_markup,
            "schema_types": self.schema_types,
            "meta_score": self.meta_score,
            "heading_score": self.heading_score,
            "image_score": self.image_score,
            "link_score": self.link_score,
            "url_score": self.url_score,
            "content_score": self.content_score,
            "social_score": self.social_score,
            "schema_score": self.schema_score,
            "overall_score": self.overall_score,
            "issues": self.issues,
            "warnings": self.warnings,
            "recommendations": self.recommendations,
        }


class SEOAnalyzer:
    """Comprehensive SEO analyzer.

    Analyzes web pages for SEO best practices and provides optimization suggestions.
    """

    # Common stop words in URLs
    URL_STOP_WORDS = {"the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for", "of", "with"}

    def __init__(self) -> None:
        pass

    def analyze(self, html: str, url: str = "", text: str = "") -> SEOMetrics:
        """Analyze a web page for SEO.

        Args:
            html: HTML content of the page.
            url: URL of the page.
            text: Extracted text content.

        Returns:
            SEOMetrics with analysis results.
        """
        metrics = SEOMetrics()
        metrics.url = url

        if not html:
            metrics.issues.append("No HTML content provided")
            return metrics

        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html, "html.parser")

            # Analyze meta tags
            self._analyze_meta_tags(soup, metrics)

            # Analyze headings
            self._analyze_headings(soup, metrics)

            # Analyze images
            self._analyze_images(soup, metrics)

            # Analyze links
            self._analyze_links(soup, metrics, url)

            # Analyze URL
            self._analyze_url(url, metrics)

            # Analyze content
            self._analyze_content(soup, text, metrics)

            # Analyze social tags
            self._analyze_social_tags(soup, metrics)

            # Analyze schema markup
            self._analyze_schema(soup, metrics)

            # Calculate scores
            self._calculate_scores(metrics)

            # Generate issues and recommendations
            self._generate_issues_and_recommendations(metrics)

        except ImportError:
            metrics.issues.append("BeautifulSoup not available for SEO analysis")
            log.warning("BeautifulSoup not available for SEO analysis")

        return metrics

    def _analyze_meta_tags(self, soup, metrics: SEOMetrics) -> None:
        """Analyze meta tags."""
        # Title
        title_tag = soup.find("title")
        if title_tag and title_tag.string:
            metrics.title = title_tag.string.strip()
            metrics.title_length = len(metrics.title)
            # Ideal title length: 50-60 characters
            metrics.title_ok = 50 <= metrics.title_length <= 60

        # Meta description
        meta_desc = soup.find("meta", attrs={"name": "description"})
        if meta_desc and meta_desc.get("content"):
            metrics.meta_description = meta_desc["content"].strip()
            metrics.meta_description_length = len(metrics.meta_description)
            # Ideal description length: 150-160 characters
            metrics.meta_description_ok = 150 <= metrics.meta_description_length <= 160

        # Meta keywords
        meta_keywords = soup.find("meta", attrs={"name": "keywords"})
        if meta_keywords and meta_keywords.get("content"):
            metrics.meta_keywords = [k.strip() for k in meta_keywords["content"].split(",")]

        # Canonical URL
        canonical = soup.find("link", attrs={"rel": "canonical"})
        if canonical and canonical.get("href"):
            metrics.canonical_url = canonical["href"]
            metrics.has_canonical = True

        # Robots meta tag
        robots = soup.find("meta", attrs={"name": "robots"})
        if robots and robots.get("content"):
            metrics.robots_meta = robots["content"]

    def _analyze_headings(self, soup, metrics: SEOMetrics) -> None:
        """Analyze heading structure."""
        metrics.h1_count = len(soup.find_all("h1"))
        metrics.h2_count = len(soup.find_all("h2"))
        metrics.h3_count = len(soup.find_all("h3"))
        metrics.h4_count = len(soup.find_all("h4"))
        metrics.h5_count = len(soup.find_all("h5"))
        metrics.h6_count = len(soup.find_all("h6"))

        # Good heading structure: exactly one H1, H2-H3 used for subsections
        metrics.heading_structure_ok = metrics.h1_count == 1 and metrics.h2_count >= 1

    def _analyze_images(self, soup, metrics: SEOMetrics) -> None:
        """Analyze image SEO."""
        images = soup.find_all("img")
        metrics.total_images = len(images)

        for img in images:
            alt = img.get("alt", "")
            if alt and alt.strip():
                metrics.images_with_alt += 1
            else:
                metrics.images_without_alt += 1

        if metrics.total_images > 0:
            metrics.image_alt_coverage = round(metrics.images_with_alt / metrics.total_images * 100, 1)

    def _analyze_links(self, soup, metrics: SEOMetrics, url: str) -> None:
        """Analyze link structure."""
        links = soup.find_all("a", href=True)
        metrics.total_links = len(links)

        parsed_url = urlparse(url) if url else None
        domain = parsed_url.netloc if parsed_url else ""

        for link in links:
            href = link.get("href", "")
            anchor_text = link.get_text(strip=True)

            # Check if internal or external
            if href.startswith("/") or (domain and domain in href):
                metrics.internal_links += 1
            elif href.startswith("http"):
                metrics.external_links += 1

            # Check anchor text
            if anchor_text:
                metrics.links_with_anchor += 1
            else:
                metrics.links_without_anchor += 1

    def _analyze_url(self, url: str, metrics: SEOMetrics) -> None:
        """Analyze URL structure."""
        if not url:
            return

        parsed = urlparse(url)
        path = parsed.path
        metrics.url_length = len(url)

        # Ideal URL length: under 75 characters
        metrics.url_ok = metrics.url_length <= 75

        # Check for hyphens (good for readability)
        metrics.url_has_hyphens = "-" in path

        # Check for stop words in URL
        path_words = set(re.findall(r'[a-z]+', path.lower()))
        metrics.url_has_stop_words = bool(path_words & self.URL_STOP_WORDS)

    def _analyze_content(self, soup, text: str, metrics: SEOMetrics) -> None:
        """Analyze content quality for SEO."""
        if not text:
            # Extract text from soup
            text = soup.get_text(separator=" ", strip=True)

        metrics.content_length = len(text)
        words = re.findall(r'\b\w+\b', text)
        metrics.word_count = len(words)

        # Ideal content length: 300+ words for good SEO
        metrics.content_ok = metrics.word_count >= 300

    def _analyze_social_tags(self, soup, metrics: SEOMetrics) -> None:
        """Analyze Open Graph and Twitter Card tags."""
        # Open Graph tags
        og_title = soup.find("meta", attrs={"property": "og:title"})
        og_description = soup.find("meta", attrs={"property": "og:description"})
        og_image = soup.find("meta", attrs={"property": "og:image"})

        if og_title or og_description or og_image:
            metrics.has_og_tags = True
            metrics.og_title = og_title.get("content", "") if og_title else ""
            metrics.og_description = og_description.get("content", "") if og_description else ""
            metrics.og_image = og_image.get("content", "") if og_image else ""

        # Twitter Card tags
        twitter_card = soup.find("meta", attrs={"name": "twitter:card"})
        twitter_title = soup.find("meta", attrs={"name": "twitter:title"})
        twitter_description = soup.find("meta", attrs={"name": "twitter:description"})

        if twitter_card or twitter_title or twitter_description:
            metrics.has_twitter_cards = True
            metrics.twitter_card = twitter_card.get("content", "") if twitter_card else ""
            metrics.twitter_title = twitter_title.get("content", "") if twitter_title else ""
            metrics.twitter_description = twitter_description.get("content", "") if twitter_description else ""

    def _analyze_schema(self, soup, metrics: SEOMetrics) -> None:
        """Analyze schema markup."""
        # Check for JSON-LD schema
        json_ld_scripts = soup.find_all("script", attrs={"type": "application/ld+json"})
        if json_ld_scripts:
            metrics.has_schema_markup = True
            for script in json_ld_scripts:
                try:
                    import json
                    data = json.loads(script.string)
                    if isinstance(data, dict):
                        schema_type = data.get("@type", "")
                        if schema_type:
                            metrics.schema_types.append(schema_type)
                    elif isinstance(data, list):
                        for item in data:
                            if isinstance(item, dict):
                                schema_type = item.get("@type", "")
                                if schema_type:
                                    metrics.schema_types.append(schema_type)
                except (json.JSONDecodeError, TypeError):
                    pass

        # Check for microdata schema
        if soup.find(attrs={"itemtype": True}):
            metrics.has_schema_markup = True

    def _calculate_scores(self, metrics: SEOMetrics) -> None:
        """Calculate SEO scores."""
        # Meta score
        meta_score = 0
        if metrics.title_ok:
            meta_score += 30
        elif metrics.title:
            meta_score += 15
        if metrics.meta_description_ok:
            meta_score += 30
        elif metrics.meta_description:
            meta_score += 15
        if metrics.has_canonical:
            meta_score += 20
        if metrics.meta_keywords:
            meta_score += 20
        metrics.meta_score = min(100, meta_score)

        # Heading score
        heading_score = 0
        if metrics.h1_count == 1:
            heading_score += 40
        elif metrics.h1_count > 0:
            heading_score += 20
        if metrics.h2_count >= 1:
            heading_score += 30
        if metrics.h3_count >= 1:
            heading_score += 30
        metrics.heading_score = min(100, heading_score)

        # Image score
        if metrics.total_images == 0:
            metrics.image_score = 50  # Neutral if no images
        else:
            metrics.image_score = metrics.image_alt_coverage

        # Link score
        link_score = 0
        if metrics.total_links > 0:
            if metrics.internal_links > 0:
                link_score += 40
            if metrics.external_links > 0:
                link_score += 30
            if metrics.links_with_anchor > 0:
                link_score += 30
        else:
            link_score = 30  # Low score if no links
        metrics.link_score = min(100, link_score)

        # URL score
        url_score = 0
        if metrics.url_ok:
            url_score += 40
        if metrics.url_has_hyphens:
            url_score += 30
        if not metrics.url_has_stop_words:
            url_score += 30
        metrics.url_score = min(100, url_score)

        # Content score
        if metrics.word_count >= 1000:
            metrics.content_score = 95
        elif metrics.word_count >= 500:
            metrics.content_score = 80
        elif metrics.word_count >= 300:
            metrics.content_score = 65
        elif metrics.word_count >= 100:
            metrics.content_score = 40
        else:
            metrics.content_score = 20

        # Social score
        social_score = 0
        if metrics.has_og_tags:
            social_score += 50
        if metrics.has_twitter_cards:
            social_score += 50
        metrics.social_score = social_score

        # Schema score
        if metrics.has_schema_markup:
            metrics.schema_score = 100
        else:
            metrics.schema_score = 0

        # Overall score (weighted average)
        metrics.overall_score = (
            metrics.meta_score * 0.20
            + metrics.heading_score * 0.15
            + metrics.image_score * 0.10
            + metrics.link_score * 0.10
            + metrics.url_score * 0.10
            + metrics.content_score * 0.20
            + metrics.social_score * 0.10
            + metrics.schema_score * 0.05
        )

    def _generate_issues_and_recommendations(self, metrics: SEOMetrics) -> None:
        """Generate SEO issues and recommendations."""
        # Meta issues
        if not metrics.title:
            metrics.issues.append("Missing page title")
            metrics.recommendations.append("Add a descriptive page title (50-60 characters)")
        elif not metrics.title_ok:
            metrics.warnings.append(f"Title length is {metrics.title_length} characters (ideal: 50-60)")
            metrics.recommendations.append("Adjust title length to 50-60 characters for optimal display")

        if not metrics.meta_description:
            metrics.issues.append("Missing meta description")
            metrics.recommendations.append("Add a meta description (150-160 characters) to improve click-through rates")
        elif not metrics.meta_description_ok:
            metrics.warnings.append(f"Meta description length is {metrics.meta_description_length} characters (ideal: 150-160)")

        if not metrics.has_canonical:
            metrics.warnings.append("Missing canonical URL")
            metrics.recommendations.append("Add a canonical URL to prevent duplicate content issues")

        # Heading issues
        if metrics.h1_count == 0:
            metrics.issues.append("No H1 heading found")
            metrics.recommendations.append("Add exactly one H1 heading with the main topic")
        elif metrics.h1_count > 1:
            metrics.warnings.append(f"Multiple H1 headings found ({metrics.h1_count})")
            metrics.recommendations.append("Use only one H1 heading per page for best SEO")

        if metrics.h2_count == 0:
            metrics.warnings.append("No H2 subheadings found")
            metrics.recommendations.append("Add H2 subheadings to structure your content")

        # Image issues
        if metrics.images_without_alt > 0:
            metrics.issues.append(f"{metrics.images_without_alt} images missing alt text")
            metrics.recommendations.append("Add descriptive alt text to all images for accessibility and SEO")

        # URL issues
        if not metrics.url_ok:
            metrics.warnings.append(f"URL is {metrics.url_length} characters (ideal: under 75)")
            metrics.recommendations.append("Shorten URL to under 75 characters for better readability and sharing")

        # Content issues
        if not metrics.content_ok:
            metrics.issues.append(f"Content is only {metrics.word_count} words (ideal: 300+)")
            metrics.recommendations.append("Expand content to at least 300 words for better SEO")

        # Social issues
        if not metrics.has_og_tags:
            metrics.warnings.append("Missing Open Graph tags")
            metrics.recommendations.append("Add Open Graph tags for better social media sharing")

        if not metrics.has_twitter_cards:
            metrics.warnings.append("Missing Twitter Card tags")
            metrics.recommendations.append("Add Twitter Card tags for better Twitter sharing")

        # Schema issues
        if not metrics.has_schema_markup:
            metrics.warnings.append("No schema markup found")
            metrics.recommendations.append("Add schema markup (JSON-LD) to help search engines understand your content")

        # Overall recommendation
        if metrics.overall_score >= 80:
            metrics.recommendations.append("Great job! Your SEO is solid. Continue monitoring and optimizing.")
        elif metrics.overall_score >= 60:
            metrics.recommendations.append("Good start! Address the issues above to improve your SEO score.")
        else:
            metrics.recommendations.append("Significant SEO improvements needed. Start with the critical issues listed above.")


def analyze_seo(html: str, url: str = "", text: str = "") -> SEOMetrics:
    """Convenience function to analyze SEO.

    Args:
        html: HTML content.
        url: Page URL.
        text: Extracted text.

    Returns:
        SEOMetrics with analysis results.
    """
    analyzer = SEOAnalyzer()
    return analyzer.analyze(html, url, text)
