"""
RSS/Atom feed parser.

Parses RSS 2.0 and Atom 1.0 feeds, extracting feed metadata and entries.
Supports common fields: title, link, description, pubDate, author, categories.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
from urllib.parse import urljoin
import httpx
from bs4 import BeautifulSoup


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
    feed_type: str = ""  # "rss" or "atom"

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


class RSSParser:
    """Parse RSS 2.0 and Atom 1.0 feeds."""

    def __init__(self, base_url: str = "") -> None:
        self.base_url = base_url

    def parse(self, xml_content: str) -> Feed:
        """Parse RSS/Atom XML content.

        Args:
            xml_content: Raw XML content of the feed.

        Returns:
            Feed object with parsed metadata and entries.
        """
        feed = Feed()
        try:
            soup = BeautifulSoup(xml_content, "xml")
        except Exception:
            try:
                soup = BeautifulSoup(xml_content, "lxml-xml")
            except Exception:
                return feed

        # Detect feed type
        if soup.find("rss"):
            feed.feed_type = "rss"
            self._parse_rss(soup, feed)
        elif soup.find("feed"):
            feed.feed_type = "atom"
            self._parse_atom(soup, feed)
        else:
            # Try to detect by namespace
            if "http://www.w3.org/2005/Atom" in xml_content:
                feed.feed_type = "atom"
                self._parse_atom(soup, feed)
            else:
                feed.feed_type = "rss"
                self._parse_rss(soup, feed)

        return feed

    def _parse_rss(self, soup: BeautifulSoup, feed: Feed) -> None:
        """Parse RSS 2.0 feed."""
        channel = soup.find("channel")
        if not channel:
            return

        # Feed metadata
        if channel.find("title"):
            feed.title = channel.find("title").get_text(strip=True)
        if channel.find("link"):
            feed.link = self._resolve_url(channel.find("link").get_text(strip=True))
        if channel.find("description"):
            feed.description = channel.find("description").get_text(strip=True)
        if channel.find("language"):
            feed.language = channel.find("language").get_text(strip=True)
        if channel.find("copyright"):
            feed.copyright = channel.find("copyright").get_text(strip=True)
        if channel.find("lastBuildDate"):
            feed.last_build_date = channel.find("lastBuildDate").get_text(strip=True)
        if channel.find("generator"):
            feed.generator = channel.find("generator").get_text(strip=True)

        # Feed image
        image = channel.find("image")
        if image and image.find("url"):
            feed.image_url = self._resolve_url(image.find("url").get_text(strip=True))

        # Items
        for item in channel.find_all("item"):
            entry = FeedEntry()

            if item.find("title"):
                entry.title = item.find("title").get_text(strip=True)
            if item.find("link"):
                entry.link = self._resolve_url(item.find("link").get_text(strip=True))
            if item.find("description"):
                entry.description = item.find("description").get_text(strip=True)
            if item.find("content:encoded"):
                entry.content = item.find("content:encoded").get_text(strip=True)
            if item.find("pubDate"):
                entry.pub_date = item.find("pubDate").get_text(strip=True)
            if item.find("author"):
                entry.author = item.find("author").get_text(strip=True)
            if item.find("guid"):
                entry.guid = item.find("guid").get_text(strip=True)

            # Categories
            for cat in item.find_all("category"):
                cat_text = cat.get_text(strip=True)
                if cat_text:
                    entry.categories.append(cat_text)

            # Media thumbnail
            media_thumbnail = item.find("media:thumbnail")
            if media_thumbnail and media_thumbnail.get("url"):
                entry.image = self._resolve_url(media_thumbnail["url"])
            else:
                enclosure = item.find("enclosure")
                if enclosure and enclosure.get("type", "").startswith("image/"):
                    entry.image = self._resolve_url(enclosure.get("url", ""))

            feed.entries.append(entry)

    def _parse_atom(self, soup: BeautifulSoup, feed: Feed) -> None:
        """Parse Atom 1.0 feed."""
        feed_elem = soup.find("feed")
        if not feed_elem:
            return

        # Feed metadata
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

        # Entries
        for entry_elem in feed_elem.find_all("entry"):
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

            feed.entries.append(entry)

    def _resolve_url(self, url: str) -> str:
        """Resolve relative URL to absolute URL."""
        if not url:
            return ""
        if url.startswith(("http://", "https://", "data:")):
            return url
        if self.base_url:
            return urljoin(self.base_url, url)
        return url


async def fetch_and_parse_feed(
    url: str,
    timeout: float = 15.0,
    user_agent: str = "webscout-mcp/0.5.0",
) -> Feed:
    """Fetch and parse an RSS/Atom feed.

    Args:
        url: Feed URL.
        timeout: Request timeout in seconds.
        user_agent: User-Agent string.

    Returns:
        Parsed Feed object.
    """
    async with httpx.AsyncClient(
        timeout=timeout,
        follow_redirects=True,
        headers={"User-Agent": user_agent},
    ) as client:
        response = await client.get(url)
        response.raise_for_status()
        parser = RSSParser(base_url=url)
        return parser.parse(response.text)


def parse_feed(xml_content: str, base_url: str = "") -> Feed:
    """Convenience function to parse RSS/Atom XML content.

    Args:
        xml_content: Raw XML content.
        base_url: Base URL for resolving relative URLs.

    Returns:
        Parsed Feed object.
    """
    parser = RSSParser(base_url=base_url)
    return parser.parse(xml_content)
