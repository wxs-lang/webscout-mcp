"""
RSS/Atom feed parser with SSRF safety, redirect protection, and auto-discovery.

Parses RSS 2.0, RSS 1.0 (RDF), and Atom 1.0 feeds. All outbound requests
pass through the project's URL safety guard (initial URL + every redirect hop).
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

from .url_safety import check_url_safe

log = logging.getLogger(__name__)

# Hard limits
DEFAULT_TIMEOUT = 15.0
DEFAULT_MAX_REDIRECTS = 5
DEFAULT_MAX_BODY_BYTES = 5 * 1024 * 1024  # 5 MB
DEFAULT_MAX_ENTRIES = 100
DEFAULT_USER_AGENT = "webscout-mcp/1.7.0 (+https://github.com/wxs-lang/webscout-mcp)"
FEED_DISCOVERY_MAX_CANDIDATES = 5

# Content types that indicate a feed
_FEED_CONTENT_TYPES = (
    "application/rss+xml",
    "application/atom+xml",
    "application/xml",
    "text/xml",
    "application/rdf+xml",
)


@dataclass
class FeedEntry:
    """A single feed entry (item)."""

    title: str = ""
    link: str = ""
    description: str = ""
    content: str = ""
    pub_date: str = ""
    author: str = ""
    categories: list[str] = field(default_factory=list)
    guid: str = ""
    image: str = ""

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "link": self.link,
            "description": self.description,
            "content": self.content,
            "pub_date": self.pub_date,
            "author": self.author,
            "categories": self.categories,
            "guid": self.guid,
            "image": self.image,
        }


@dataclass
class Feed:
    """Parsed RSS/Atom feed."""

    title: str = ""
    link: str = ""
    description: str = ""
    language: str = ""
    copyright: str = ""
    last_build_date: str = ""
    generator: str = ""
    image_url: str = ""
    entries: list[FeedEntry] = field(default_factory=list)
    feed_type: str = ""  # "rss", "atom", or "rdf"

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "link": self.link,
            "description": self.description,
            "language": self.language,
            "copyright": self.copyright,
            "last_build_date": self.last_build_date,
            "generator": self.generator,
            "image_url": self.image_url,
            "feed_type": self.feed_type,
            "entry_count": len(self.entries),
            "entries": [e.to_dict() for e in self.entries],
        }


class RSSParseError(Exception):
    """Raised when feed parsing fails for a structural reason."""


class RSSParser:
    """Parse RSS 2.0, RSS 1.0 (RDF), and Atom 1.0 feeds."""

    def __init__(self, base_url: str = "") -> None:
        self.base_url = base_url

    def parse(self, xml_content: str) -> Feed:
        """Parse RSS/Atom XML content.

        Args:
            xml_content: Raw XML content of the feed.

        Returns:
            Feed object with parsed metadata and entries.

        Raises:
            RSSParseError: If the content is not a recognizable feed.
        """
        if not xml_content or not xml_content.strip():
            raise RSSParseError("Empty feed content")

        soup = self._make_soup(xml_content)
        if soup is None:
            raise RSSParseError("Malformed XML / not parseable as feed")

        feed = Feed()

        # Detect feed type
        if soup.find("rss"):
            feed.feed_type = "rss"
            self._parse_rss(soup, feed)
        elif soup.find("feed"):
            feed.feed_type = "atom"
            self._parse_atom(soup, feed)
        elif soup.find("RDF") or soup.find("rdf:RDF"):
            feed.feed_type = "rdf"
            self._parse_rdf(soup, feed)
        else:
            # Try namespace-based detection
            if "http://www.w3.org/2005/Atom" in xml_content:
                feed.feed_type = "atom"
                self._parse_atom(soup, feed)
            elif "http://purl.org/rss/1.0/" in xml_content:
                feed.feed_type = "rdf"
                self._parse_rdf(soup, feed)
            else:
                raise RSSParseError("Content is not a recognizable RSS/Atom/RDF feed")

        return feed

    @staticmethod
    def _make_soup(xml_content: str) -> BeautifulSoup | None:
        """Create a BeautifulSoup parser with XXE protection."""
        try:
            # lxml-xml disables external entity resolution by default (lxml >= 3.0)
            return BeautifulSoup(xml_content, "lxml-xml")
        except Exception:
            try:
                return BeautifulSoup(xml_content, "xml")
            except Exception:
                return None

    def _parse_rss(self, soup: BeautifulSoup, feed: Feed) -> None:
        """Parse RSS 2.0 feed."""
        channel = soup.find("channel")
        if not channel:
            return

        self._parse_channel_metadata(channel, feed)

        # Items
        for item in channel.find_all("item"):
            entry = self._parse_rss_item(item)
            if entry:
                feed.entries.append(entry)

    def _parse_rdf(self, soup: BeautifulSoup, feed: Feed) -> None:
        """Parse RSS 1.0 (RDF) feed."""
        channel = soup.find("channel")
        if channel:
            self._parse_channel_metadata(channel, feed)

        # RDF items are direct children of rdf:RDF, not inside channel
        rdf_root = soup.find("RDF") or soup.find("rdf:RDF")
        item_container = rdf_root if rdf_root else soup
        for item in item_container.find_all("item"):
            entry = self._parse_rss_item(item)
            if entry:
                feed.entries.append(entry)

    def _parse_channel_metadata(self, channel, feed: Feed) -> None:
        """Parse common channel metadata (RSS 2.0 and RDF 1.0)."""
        if channel.find("title"):
            feed.title = channel.find("title").get_text(strip=True)
        if channel.find("link"):
            link_text = channel.find("link").get_text(strip=True)
            # RDF 1.0 uses rdf:resource attribute for link
            if not link_text:
                link_text = channel.find("link").get("rdf:resource", "")
            feed.link = self._resolve_url(link_text)
        if channel.find("description"):
            feed.description = channel.find("description").get_text(strip=True)
        if channel.find("language"):
            feed.language = channel.find("language").get_text(strip=True)
        if channel.find("copyright") or channel.find("dc:rights"):
            rights = channel.find("copyright") or channel.find("dc:rights")
            feed.copyright = rights.get_text(strip=True)
        if channel.find("lastBuildDate") or channel.find("dc:date"):
            date = channel.find("lastBuildDate") or channel.find("dc:date")
            feed.last_build_date = date.get_text(strip=True)
        if channel.find("generator"):
            feed.generator = channel.find("generator").get_text(strip=True)

        # Feed image
        image = channel.find("image")
        if image:
            if image.find("url"):
                feed.image_url = self._resolve_url(image.find("url").get_text(strip=True))
            elif image.get("rdf:resource"):
                feed.image_url = self._resolve_url(image["rdf:resource"])

    def _parse_rss_item(self, item) -> FeedEntry | None:
        """Parse a single RSS/RDF item element."""
        entry = FeedEntry()

        if item.find("title"):
            entry.title = item.find("title").get_text(strip=True)
        if item.find("link"):
            link_text = item.find("link").get_text(strip=True)
            if not link_text:
                link_text = item.find("link").get("rdf:resource", "")
            entry.link = self._resolve_url(link_text)
        if item.find("description"):
            entry.description = item.find("description").get_text(strip=True)
        # content:encoded — try with namespace prefix, then bare tag name
        content_encoded = item.find("content:encoded") or item.find("encoded")
        if content_encoded:
            entry.content = content_encoded.get_text(strip=True)
        if item.find("pubDate"):
            entry.pub_date = item.find("pubDate").get_text(strip=True)
        elif item.find("dc:date"):
            entry.pub_date = item.find("dc:date").get_text(strip=True)
        if item.find("author"):
            entry.author = item.find("author").get_text(strip=True)
        elif item.find("dc:creator"):
            entry.author = item.find("dc:creator").get_text(strip=True)
        if item.find("guid"):
            entry.guid = item.find("guid").get_text(strip=True)
        elif item.find("dc:identifier"):
            entry.guid = item.find("dc:identifier").get_text(strip=True)

        # Categories
        for cat in item.find_all("category"):
            cat_text = cat.get_text(strip=True)
            if cat_text:
                entry.categories.append(cat_text)
        for cat in item.find_all("dc:subject"):
            cat_text = cat.get_text(strip=True)
            if cat_text:
                entry.categories.append(cat_text)

        # Media thumbnail / enclosure
        media_thumbnail = item.find("media:thumbnail")
        if media_thumbnail and media_thumbnail.get("url"):
            entry.image = self._resolve_url(media_thumbnail["url"])
        else:
            enclosure = item.find("enclosure")
            if enclosure and enclosure.get("type", "").startswith("image/"):
                entry.image = self._resolve_url(enclosure.get("url", ""))

        # Skip completely empty entries
        if not any([entry.title, entry.link, entry.description, entry.guid]):
            return None
        return entry

    def _parse_atom(self, soup: BeautifulSoup, feed: Feed) -> None:
        """Parse Atom 1.0 feed."""
        feed_elem = soup.find("feed")
        if not feed_elem:
            return

        if feed_elem.find("title"):
            feed.title = feed_elem.find("title").get_text(strip=True)

        # Link (rel="alternate")
        for link in feed_elem.find_all("link"):
            rel = link.get("rel", "alternate")
            if rel == "alternate" and link.get("href"):
                feed.link = self._resolve_url(link["href"])
                break

        if feed_elem.find("subtitle"):
            feed.description = feed_elem.find("subtitle").get_text(strip=True)
        if feed_elem.find("rights"):
            feed.copyright = feed_elem.find("rights").get_text(strip=True)
        if feed_elem.find("updated"):
            feed.last_build_date = feed_elem.find("updated").get_text(strip=True)
        if feed_elem.find("generator"):
            feed.generator = feed_elem.find("generator").get_text(strip=True)
        if feed_elem.find("language"):
            feed.language = feed_elem.find("language").get_text(strip=True)

        # Feed logo/icon
        if feed_elem.find("logo"):
            feed.image_url = self._resolve_url(feed_elem.find("logo").get_text(strip=True))
        elif feed_elem.find("icon"):
            feed.image_url = self._resolve_url(feed_elem.find("icon").get_text(strip=True))

        # Entries
        for entry_elem in feed_elem.find_all("entry"):
            entry = self._parse_atom_entry(entry_elem)
            if entry:
                feed.entries.append(entry)

    def _parse_atom_entry(self, entry_elem) -> FeedEntry | None:
        """Parse a single Atom entry element."""
        entry = FeedEntry()

        if entry_elem.find("title"):
            entry.title = entry_elem.find("title").get_text(strip=True)

        # Link (rel="alternate")
        for link in entry_elem.find_all("link"):
            rel = link.get("rel", "alternate")
            if rel == "alternate" and link.get("href"):
                entry.link = self._resolve_url(link["href"])
                break

        if entry_elem.find("summary"):
            entry.description = entry_elem.find("summary").get_text(strip=True)
        if entry_elem.find("content"):
            entry.content = entry_elem.find("content").get_text(strip=True)
        if entry_elem.find("published"):
            entry.pub_date = entry_elem.find("published").get_text(strip=True)
        elif entry_elem.find("updated"):
            entry.pub_date = entry_elem.find("updated").get_text(strip=True)

        # Author
        author = entry_elem.find("author")
        if author and author.find("name"):
            entry.author = author.find("name").get_text(strip=True)

        # ID
        if entry_elem.find("id"):
            entry.guid = entry_elem.find("id").get_text(strip=True)

        # Categories
        for cat in entry_elem.find_all("category"):
            term = cat.get("term", "")
            if term:
                entry.categories.append(term)

        # Media thumbnail
        media_thumbnail = entry_elem.find("media:thumbnail")
        if media_thumbnail and media_thumbnail.get("url"):
            entry.image = self._resolve_url(media_thumbnail["url"])

        # Skip completely empty entries
        if not any([entry.title, entry.link, entry.description, entry.guid]):
            return None
        return entry

    def _resolve_url(self, url: str) -> str:
        """Resolve relative URL to absolute URL."""
        if not url:
            return ""
        if url.startswith(("http://", "https://", "data:", "mailto:")):
            return url
        if self.base_url:
            return urljoin(self.base_url, url)
        return url


def _create_safe_client(
    *,
    timeout: float,
    max_redirects: int,
    user_agent: str,
    allow_private: bool = False,
) -> httpx.AsyncClient:
    """Create an httpx client with per-request SSRF event hook."""

    async def _ssrf_hook(request: httpx.Request) -> None:
        result = await asyncio.to_thread(check_url_safe, str(request.url), allow_private=allow_private)
        if not result.safe:
            raise ValueError(f"SSRF blocked: {result.reason}")

    return httpx.AsyncClient(
        timeout=timeout,
        follow_redirects=True,
        max_redirects=max_redirects,
        headers={"User-Agent": user_agent},
        event_hooks={"request": [_ssrf_hook]},
    )


async def _fetch_with_size_limit(
    client: httpx.AsyncClient,
    url: str,
    max_body_bytes: int,
) -> tuple[str, str, int]:
    """Fetch URL with streaming size limit.

    Returns:
        Tuple of (text_content, final_url, status_code).

    Raises:
        ValueError: If response body exceeds max_body_bytes.
        httpx.HTTPError: On HTTP errors.
    """
    async with client.stream("GET", url) as resp:
        resp.raise_for_status()
        final_url = str(resp.url)
        status_code = resp.status_code

        # Read with size limit
        chunks: list[bytes] = []
        total = 0
        async for chunk in resp.aiter_bytes(chunk_size=8192):
            total += len(chunk)
            if total > max_body_bytes:
                raise ValueError(f"Response body exceeds maximum size of {max_body_bytes} bytes")
            chunks.append(chunk)

        raw = b"".join(chunks)

        # Detect encoding from Content-Type or XML declaration
        content_type = resp.headers.get("content-type", "")
        encoding = None
        if "charset=" in content_type:
            encoding = content_type.split("charset=")[-1].split(";")[0].strip()

        try:
            text = raw.decode(encoding or "utf-8", errors="replace")
        except (LookupError, UnicodeDecodeError):
            text = raw.decode("utf-8", errors="replace")

        return text, final_url, status_code


def _looks_like_feed(text: str, content_type: str = "") -> bool:
    """Quick heuristic to determine if content is a feed.

    Checks content-type first, then inspects the beginning of the content
    for XML declaration or feed root elements. Does NOT match on substrings
    like "application/rss+xml" that may appear inside HTML link tags.
    """
    if content_type and any(ct in content_type for ct in _FEED_CONTENT_TYPES):
        return True
    stripped = text.lstrip()[:1000].lower()
    # Must start with XML declaration or a feed root element
    return any(stripped.startswith(marker) for marker in ("<?xml", "<rss", "<feed", "<rdf:rdf"))


def _discover_feed_urls(html: str, base_url: str) -> list[str]:
    """Discover RSS/Atom feed URLs from HTML link rel=alternate tags."""
    try:
        soup = BeautifulSoup(html, "html.parser")
    except Exception:
        return []

    candidates: list[str] = []
    for link in soup.find_all("link", rel="alternate"):
        href = link.get("href", "")
        link_type = link.get("type", "").lower()
        if not href:
            continue
        if "rss" in link_type or "atom" in link_type or "xml" in link_type:
            absolute = urljoin(base_url, href)
            if absolute not in candidates:
                candidates.append(absolute)
            if len(candidates) >= FEED_DISCOVERY_MAX_CANDIDATES:
                break
    return candidates


async def fetch_and_parse_feed(
    url: str,
    max_entries: int = 20,
    *,
    timeout: float = DEFAULT_TIMEOUT,
    user_agent: str = DEFAULT_USER_AGENT,
    max_redirects: int = DEFAULT_MAX_REDIRECTS,
    max_body_bytes: int = DEFAULT_MAX_BODY_BYTES,
    allow_private: bool = False,
) -> Feed:
    """Fetch and parse an RSS/Atom/RDF feed with SSRF safety.

    Args:
        url: Feed URL or HTML page URL (auto-discovery will be attempted).
        max_entries: Maximum number of entries to return (1-100).
        timeout: Request timeout in seconds.
        user_agent: User-Agent string.
        max_redirects: Maximum redirect hops.
        max_body_bytes: Maximum response body size in bytes.
        allow_private: If True, skip SSRF checks (opt-in only).

    Returns:
        Parsed Feed object.

    Raises:
        ValueError: If URL is unsafe or response too large.
        RSSParseError: If content is not a recognizable feed.
        httpx.HTTPError: On HTTP errors.
    """
    # Clamp max_entries
    max_entries = max(1, min(max_entries, DEFAULT_MAX_ENTRIES))

    # Initial URL safety check (before any network request)
    safety = check_url_safe(url, allow_private=allow_private)
    if not safety.safe:
        raise ValueError(f"SSRF blocked (initial URL): {safety.reason}")

    async with _create_safe_client(
        timeout=timeout,
        max_redirects=max_redirects,
        user_agent=user_agent,
        allow_private=allow_private,
    ) as client:
        # First attempt: fetch the URL directly
        text, final_url, status_code = await _fetch_with_size_limit(client, url, max_body_bytes)

        # If it looks like a feed, parse it
        content_type = ""
        if _looks_like_feed(text, content_type):
            parser = RSSParser(base_url=final_url)
            feed = parser.parse(text)
            feed.entries = feed.entries[:max_entries]
            return feed

        # Otherwise, try HTML feed auto-discovery
        feed_candidates = _discover_feed_urls(text, final_url)
        last_error: Exception | None = None

        for feed_url in feed_candidates:
            # Safety check each discovered URL
            feed_safety = check_url_safe(feed_url, allow_private=allow_private)
            if not feed_safety.safe:
                log.warning("Discovered feed URL blocked by SSRF: %s", feed_safety.reason)
                continue

            try:
                feed_text, feed_final_url, _ = await _fetch_with_size_limit(client, feed_url, max_body_bytes)
                if _looks_like_feed(feed_text):
                    parser = RSSParser(base_url=feed_final_url)
                    feed = parser.parse(feed_text)
                    feed.entries = feed.entries[:max_entries]
                    return feed
            except (RSSParseError, ValueError, httpx.HTTPError) as exc:
                last_error = exc
                continue

        # No feed found — raise with clear error
        if last_error:
            raise RSSParseError(f"URL is not a feed and feed auto-discovery failed: {last_error}")
        raise RSSParseError("URL is not a recognizable feed and no RSS/Atom link was found in HTML")


def parse_feed(xml_content: str, base_url: str = "") -> Feed:
    """Convenience function to parse RSS/Atom XML content.

    Args:
        xml_content: Raw XML content.
        base_url: Base URL for resolving relative URLs.

    Returns:
        Parsed Feed object.

    Raises:
        RSSParseError: If content is not a recognizable feed.
    """
    parser = RSSParser(base_url=base_url)
    return parser.parse(xml_content)
