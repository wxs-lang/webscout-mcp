"""
Metadata extractor for web pages.

Extracts common metadata from HTML:
- Basic: title, description, keywords, author, language
- Open Graph: og:title, og:description, og:image, og:url, og:type
- Twitter: twitter:card, twitter:title, twitter:description, twitter:image
- Structural: canonical URL, favicon, robots meta
- Links: all canonical, alternate, prev/next links
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from urllib.parse import urljoin

from bs4 import BeautifulSoup

log = logging.getLogger(__name__)

# Hard limits to prevent resource exhaustion
MAX_RAW_META_TAGS = 200
MAX_JSON_LD_ENTRIES = 50
MAX_IMAGES = 100
MAX_LINKS = 200
MAX_JSON_LD_DEPTH = 3  # recursion depth for @graph / nested arrays


@dataclass
class PageMetadata:
    """Extracted page metadata."""

    title: str = ""
    description: str = ""
    keywords: list[str] = field(default_factory=list)
    author: str = ""
    language: str = ""
    canonical_url: str = ""
    favicon: str = ""
    robots: str = ""
    # Open Graph
    og_title: str = ""
    og_description: str = ""
    og_image: str = ""
    og_url: str = ""
    og_type: str = ""
    og_site_name: str = ""
    # Twitter
    twitter_card: str = ""
    twitter_title: str = ""
    twitter_description: str = ""
    twitter_image: str = ""
    twitter_creator: str = ""
    # Additional
    viewport: str = ""
    charset: str = ""
    generator: str = ""
    theme_color: str = ""
    # Raw meta tags (for custom extraction)
    raw_meta: dict[str, str] = field(default_factory=dict)
    # JSON-LD structured data
    json_ld: list[dict] = field(default_factory=list)
    # Article metadata
    article_author: str = ""
    article_published_time: str = ""
    article_modified_time: str = ""
    article_section: str = ""
    article_tags: list[str] = field(default_factory=list)
    # Images
    images: list[dict] = field(default_factory=list)
    # Links
    links: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "title": self.title,
            "description": self.description,
            "keywords": self.keywords,
            "author": self.author,
            "language": self.language,
            "canonical_url": self.canonical_url,
            "favicon": self.favicon,
            "robots": self.robots,
            "open_graph": {
                "title": self.og_title,
                "description": self.og_description,
                "image": self.og_image,
                "url": self.og_url,
                "type": self.og_type,
                "site_name": self.og_site_name,
            },
            "twitter": {
                "card": self.twitter_card,
                "title": self.twitter_title,
                "description": self.twitter_description,
                "image": self.twitter_image,
                "creator": self.twitter_creator,
            },
            "technical": {
                "viewport": self.viewport,
                "charset": self.charset,
                "generator": self.generator,
                "theme_color": self.theme_color,
            },
            "raw_meta": self.raw_meta,
            "json_ld": self.json_ld,
            "article": {
                "author": self.article_author,
                "published_time": self.article_published_time,
                "modified_time": self.article_modified_time,
                "section": self.article_section,
                "tags": self.article_tags,
            },
            "images": self.images,
            "links": self.links,
        }

    def get_best_title(self) -> str:
        """Get the best available title (OG > Twitter > HTML title)."""
        return self.og_title or self.twitter_title or self.title

    def get_best_description(self) -> str:
        """Get the best available description (OG > Twitter > meta description)."""
        return self.og_description or self.twitter_description or self.description

    def get_best_image(self) -> str:
        """Get the best available image (OG > Twitter)."""
        return self.og_image or self.twitter_image


class MetadataExtractor:
    """Extract metadata from HTML content."""

    def __init__(self, base_url: str = "") -> None:
        self.base_url = base_url

    def extract(self, html: str, base_url: str | None = None) -> PageMetadata:
        """Extract all metadata from HTML.

        Args:
            html: Raw HTML content.
            base_url: Optional base URL for resolving relative URLs. If provided,
                overrides the base_url set in the constructor. This makes the
                method compatible with callers that pass base_url as a keyword
                argument (e.g. server.py metadata_extract tool).

        Returns:
            PageMetadata with all extracted fields.
        """
        if base_url is not None:
            self.base_url = base_url

        metadata = PageMetadata()
        try:
            soup = BeautifulSoup(html, "lxml")
        except Exception:
            return metadata

        # HTML title
        if soup.title and soup.title.string:
            metadata.title = soup.title.string.strip()

        # HTML language
        if soup.html and soup.html.get("lang"):
            metadata.language = soup.html["lang"]

        # Charset
        charset_meta = soup.find("meta", attrs={"charset": True})
        if charset_meta:
            metadata.charset = charset_meta["charset"]

        # Extract all meta tags (with hard limit)
        meta_tags = soup.find_all("meta")
        for tag in meta_tags[:MAX_RAW_META_TAGS]:
            name = tag.get("name", "").lower()
            property_attr = tag.get("property", "").lower()
            content = tag.get("content", "").strip()
            key = name or property_attr

            if key and content and len(metadata.raw_meta) < MAX_RAW_META_TAGS:
                metadata.raw_meta[key] = content

            # Basic meta (name attribute)
            if name == "description":
                metadata.description = content
            elif name == "keywords":
                metadata.keywords = [k.strip() for k in content.split(",") if k.strip()]
            elif name == "author":
                metadata.author = content
            elif name == "robots":
                metadata.robots = content
            elif name == "viewport":
                metadata.viewport = content
            elif name == "generator":
                metadata.generator = content
            elif name == "theme-color":
                metadata.theme_color = content

            # Article metadata — can appear in BOTH name and property attributes
            article_key = (
                name if name.startswith("article:") else property_attr if property_attr.startswith("article:") else ""
            )
            if article_key == "article:author":
                metadata.article_author = content
            elif article_key == "article:published_time":
                metadata.article_published_time = content
            elif article_key == "article:modified_time":
                metadata.article_modified_time = content
            elif article_key == "article:section":
                metadata.article_section = content
            elif article_key == "article:tag":
                metadata.article_tags.append(content)

            # Open Graph (property attribute)
            if property_attr == "og:title":
                metadata.og_title = content
            elif property_attr == "og:description":
                metadata.og_description = content
            elif property_attr == "og:image":
                metadata.og_image = self._resolve_url(content)
            elif property_attr == "og:url":
                metadata.og_url = self._resolve_url(content)
            elif property_attr == "og:type":
                metadata.og_type = content
            elif property_attr == "og:site_name":
                metadata.og_site_name = content

            # Twitter (name attribute)
            if name == "twitter:card":
                metadata.twitter_card = content
            elif name == "twitter:title":
                metadata.twitter_title = content
            elif name == "twitter:description":
                metadata.twitter_description = content
            elif name == "twitter:image":
                metadata.twitter_image = self._resolve_url(content)
            elif name == "twitter:creator":
                metadata.twitter_creator = content

        # Canonical URL
        canonical = soup.find("link", rel="canonical")
        if canonical and canonical.get("href"):
            metadata.canonical_url = self._resolve_url(canonical["href"])

        # Favicon
        favicon = soup.find("link", rel=lambda x: x and "icon" in x.lower())
        if favicon and favicon.get("href"):
            metadata.favicon = self._resolve_url(favicon["href"])

        # JSON-LD structured data (with @graph support and hard limits)
        json_ld_scripts = soup.find_all("script", type="application/ld+json")
        for script in json_ld_scripts:
            if script.string and len(metadata.json_ld) < MAX_JSON_LD_ENTRIES:
                try:
                    data = json.loads(script.string.strip())
                    self._flatten_json_ld(data, metadata.json_ld, depth=0)
                except (json.JSONDecodeError, ValueError, TypeError) as exc:
                    log.debug("Malformed JSON-LD skipped: %s", exc)

        # Images extraction (with hard limit)
        img_tags = soup.find_all("img")
        for img in img_tags[:MAX_IMAGES]:
            src = img.get("src", "")
            if not src:
                continue
            image_info = {
                "src": self._resolve_url(src),
                "alt": img.get("alt", ""),
                "title": img.get("title", ""),
                "width": img.get("width", ""),
                "height": img.get("height", ""),
            }
            if image_info["src"] and len(metadata.images) < MAX_IMAGES:
                metadata.images.append(image_info)

        # Links extraction (with hard limit)
        a_tags = soup.find_all("a", href=True)
        for a in a_tags[:MAX_LINKS]:
            href = a.get("href", "")
            if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
                continue
            link_info = {
                "href": self._resolve_url(href),
                "text": a.get_text(strip=True)[:200],
                "title": a.get("title", ""),
                "rel": a.get("rel", ""),
                "target": a.get("target", ""),
            }
            if link_info["href"] and len(metadata.links) < MAX_LINKS:
                metadata.links.append(link_info)

        return metadata

    def _flatten_json_ld(self, data: object, target: list[dict], depth: int = 0) -> None:
        """Flatten JSON-LD data, expanding @graph arrays and nested lists.

        Handles:
        - dict with @graph key (schema.org graph)
        - list of nodes
        - single dict node
        Recursion is bounded by MAX_JSON_LD_DEPTH to prevent stack exhaustion.
        """
        if depth > MAX_JSON_LD_DEPTH or len(target) >= MAX_JSON_LD_ENTRIES:
            return
        if isinstance(data, list):
            for item in data:
                if len(target) >= MAX_JSON_LD_ENTRIES:
                    break
                self._flatten_json_ld(item, target, depth + 1)
        elif isinstance(data, dict):
            # If the dict has an @graph key, expand its contents as separate nodes
            if "@graph" in data and isinstance(data["@graph"], list):
                # Keep the outer dict too (it may have @context etc.)
                if len(target) < MAX_JSON_LD_ENTRIES:
                    target.append(data)
                for node in data["@graph"]:
                    if len(target) >= MAX_JSON_LD_ENTRIES:
                        break
                    self._flatten_json_ld(node, target, depth + 1)
            else:
                target.append(data)

    def _resolve_url(self, url: str) -> str:
        """Resolve relative URL to absolute URL."""
        if not url:
            return ""
        if url.startswith(("http://", "https://", "data:")):
            return url
        if self.base_url:
            return urljoin(self.base_url, url)
        return url


def extract_metadata(html: str, base_url: str = "") -> PageMetadata:
    """Convenience function to extract metadata from HTML.

    Args:
        html: Raw HTML content.
        base_url: Base URL for resolving relative URLs.

    Returns:
        PageMetadata with all extracted fields.
    """
    extractor = MetadataExtractor(base_url=base_url)
    return extractor.extract(html)
