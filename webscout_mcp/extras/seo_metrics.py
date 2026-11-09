"""SEO signal extraction for site comparison.

`competitor_analyzer.CompetitorAnalyzer._apply_seo_metrics` reads a specific set of
keys that no existing analyzer emits:

    title_length, meta_description_length, heading_count, h1_count,
    image_count, images_with_alt, internal_links, external_links,
    has_schema, has_og_tags, has_twitter_cards, canonical_url

`content_quality` reports a different vocabulary (`has_title`, `link_count`), so passing
it produced the base SEO score of 50 for every site - a silent zero that made a rich page
and a stub indistinguishable. This module supplies the expected shape.

Deliberate choices:
- `heading_count` counts h1 and h2, since that is the outline a reader scans.
- links are split by host: a link to the same host is internal, anything else external.
  Fragment and mailto links are skipped rather than counted as internal.
- `images_with_alt` requires a non-empty alt attribute; `alt=""` is decorative and does
  not satisfy accessibility intent.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

__all__ = ["extract_seo_metrics"]

_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.DOTALL | re.IGNORECASE)
_META_DESC_RE = re.compile(r'<meta\s+name=["\']description["\']\s+content=["\'](.*?)["\']', re.IGNORECASE | re.DOTALL)
_H1_RE = re.compile(r"<h1[^>]*>", re.IGNORECASE)
_H12_RE = re.compile(r"<h[12][^>]*>", re.IGNORECASE)
_IMG_RE = re.compile(r"<img\b[^>]*>", re.IGNORECASE)
_ALT_RE = re.compile(r'\balt\s*=\s*["\'][^"\']+["\']', re.IGNORECASE)
_HREF_RE = re.compile(r'<a\b[^>]*href=["\']([^"\']+)["\']', re.IGNORECASE)
_CANONICAL_RE = re.compile(r'<link\s+rel=["\']canonical["\'][^>]*href=["\']([^"\']+)["\']', re.IGNORECASE)


def extract_seo_metrics(html: str, base_url: str = "") -> dict[str, Any]:
    """Return the SEO metric dict `_apply_seo_metrics` expects.

    Args:
        html: Raw page markup.
        base_url: Used to decide whether a link is internal.

    Returns:
        Dict with the twelve keys the analyzer reads, never raising on malformed markup.
    """
    if not html:
        return {
            "title_length": 0,
            "meta_description_length": 0,
            "heading_count": 0,
            "h1_count": 0,
            "image_count": 0,
            "images_with_alt": 0,
            "internal_links": 0,
            "external_links": 0,
            "has_schema": False,
            "has_og_tags": False,
            "has_twitter_cards": False,
            "canonical_url": "",
        }

    low = html.lower()
    host = urlparse(base_url).netloc if base_url else ""

    title_match = _TITLE_RE.search(html)
    title = title_match.group(1).strip() if title_match else ""

    meta_match = _META_DESC_RE.search(html)
    meta_description = meta_match.group(1).strip() if meta_match else ""

    images = _IMG_RE.findall(html)
    images_with_alt = [tag for tag in images if _ALT_RE.search(tag)]

    internal = external = 0
    for href in _HREF_RE.findall(html):
        if href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue
        if href.startswith(("http://", "https://", "//")):
            if host and host in href:
                internal += 1
            else:
                external += 1
        else:
            internal += 1

    canonical_match = _CANONICAL_RE.search(html)

    return {
        "title_length": len(title),
        "meta_description_length": len(meta_description),
        "heading_count": len(_H12_RE.findall(low)),
        "h1_count": len(_H1_RE.findall(low)),
        "image_count": len(images),
        "images_with_alt": len(images_with_alt),
        "internal_links": internal,
        "external_links": external,
        "has_schema": "application/ld+json" in low or "itemtype" in low,
        "has_og_tags": 'property="og:' in low or "property='og:" in low,
        "has_twitter_cards": 'name="twitter:' in low or "name='twitter:" in low,
        "canonical_url": canonical_match.group(1) if canonical_match else "",
    }
