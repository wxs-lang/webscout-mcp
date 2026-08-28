"""
Tests for rss_parser module.
"""

import pytest

from webscout_mcp.rss_parser import (
    Feed,
    FeedEntry,
    RSSParser,
    parse_feed,
)


class TestFeedEntry:
    """Tests for FeedEntry dataclass."""

    def test_default_values(self):
        """Test default values."""
        entry = FeedEntry()
        assert entry.title == ""
        assert entry.link == ""
        assert entry.description == ""
        assert entry.content == ""
        assert entry.pub_date == ""
        assert entry.author == ""
        assert entry.categories == []
        assert entry.guid == ""
        assert entry.image == ""

    def test_to_dict(self):
        """Test to_dict method."""
        entry = FeedEntry(
            title="Test Entry",
            link="https://example.com/entry",
            description="Test description",
            pub_date="2024-01-01",
            author="Test Author",
            categories=["python", "test"],
            guid="12345",
        )
        data = entry.to_dict()
        assert data["title"] == "Test Entry"
        assert data["link"] == "https://example.com/entry"
        assert data["description"] == "Test description"
        assert data["pub_date"] == "2024-01-01"
        assert data["author"] == "Test Author"
        assert data["categories"] == ["python", "test"]
        assert data["guid"] == "12345"


class TestFeed:
    """Tests for Feed dataclass."""

    def test_default_values(self):
        """Test default values."""
        feed = Feed()
        assert feed.title == ""
        assert feed.link == ""
        assert feed.description == ""
        assert feed.language == ""
        assert feed.copyright == ""
        assert feed.last_build_date == ""
        assert feed.generator == ""
        assert feed.image_url == ""
        assert feed.entries == []
        assert feed.feed_type == ""

    def test_to_dict(self):
        """Test to_dict method."""
        feed = Feed(
            title="Test Feed",
            link="https://example.com/feed",
            description="Test feed description",
            language="en",
            feed_type="rss",
            entries=[FeedEntry(title="Entry 1"), FeedEntry(title="Entry 2")],
        )
        data = feed.to_dict()
        assert data["title"] == "Test Feed"
        assert data["link"] == "https://example.com/feed"
        assert data["description"] == "Test feed description"
        assert data["language"] == "en"
        assert data["feed_type"] == "rss"
        assert data["entry_count"] == 2
        assert len(data["entries"]) == 2


class TestRSSParser:
    """Tests for RSSParser class."""

    def test_parse_rss_20(self):
        """Test parsing RSS 2.0 feed."""
        rss_xml = """<?xml version="1.0" encoding="UTF-8"?>
        <rss version="2.0">
          <channel>
            <title>Test RSS Feed</title>
            <link>https://example.com</link>
            <description>A test RSS feed</description>
            <language>en-us</language>
            <copyright>2024 Test</copyright>
            <lastBuildDate>Mon, 01 Jan 2024 00:00:00 GMT</lastBuildDate>
            <generator>TestGenerator</generator>
            <image>
              <url>https://example.com/image.jpg</url>
              <title>Test Image</title>
              <link>https://example.com</link>
            </image>
            <item>
              <title>First Item</title>
              <link>https://example.com/first</link>
              <description>First item description</description>
              <pubDate>Mon, 01 Jan 2024 00:00:00 GMT</pubDate>
              <author>author@example.com</author>
              <guid>12345</guid>
              <category>python</category>
              <category>testing</category>
            </item>
            <item>
              <title>Second Item</title>
              <link>https://example.com/second</link>
              <description>Second item description</description>
              <pubDate>Tue, 02 Jan 2024 00:00:00 GMT</pubDate>
            </item>
          </channel>
        </rss>
        """
        parser = RSSParser()
        feed = parser.parse(rss_xml)
        assert feed.feed_type == "rss"
        assert feed.title == "Test RSS Feed"
        assert feed.link == "https://example.com"
        assert feed.description == "A test RSS feed"
        assert feed.language == "en-us"
        assert feed.copyright == "2024 Test"
        assert feed.last_build_date == "Mon, 01 Jan 2024 00:00:00 GMT"
        assert feed.generator == "TestGenerator"
        assert feed.image_url == "https://example.com/image.jpg"
        assert len(feed.entries) == 2

        # First entry
        assert feed.entries[0].title == "First Item"
        assert feed.entries[0].link == "https://example.com/first"
        assert feed.entries[0].description == "First item description"
        assert feed.entries[0].pub_date == "Mon, 01 Jan 2024 00:00:00 GMT"
        assert feed.entries[0].author == "author@example.com"
        assert feed.entries[0].guid == "12345"
        assert feed.entries[0].categories == ["python", "testing"]

        # Second entry
        assert feed.entries[1].title == "Second Item"

    def test_parse_atom_10(self):
        """Test parsing Atom 1.0 feed."""
        atom_xml = """<?xml version="1.0" encoding="UTF-8"?>
        <feed xmlns="http://www.w3.org/2005/Atom">
          <title>Test Atom Feed</title>
          <link href="https://example.com/feed" rel="self"/>
          <link href="https://example.com" rel="alternate"/>
          <subtitle>A test Atom feed</subtitle>
          <rights>2024 Test</rights>
          <updated>2024-01-01T00:00:00Z</updated>
          <generator>TestGenerator</generator>
          <entry>
            <title>First Entry</title>
            <link href="https://example.com/first" rel="alternate"/>
            <id>urn:uuid:12345</id>
            <published>2024-01-01T00:00:00Z</published>
            <updated>2024-01-02T00:00:00Z</updated>
            <summary>First entry summary</summary>
            <content>First entry content</content>
            <author>
              <name>Test Author</name>
            </author>
            <category term="python"/>
            <category term="testing"/>
          </entry>
        </feed>
        """
        parser = RSSParser()
        feed = parser.parse(atom_xml)
        assert feed.feed_type == "atom"
        assert feed.title == "Test Atom Feed"
        assert feed.link == "https://example.com"
        assert feed.description == "A test Atom feed"
        assert feed.copyright == "2024 Test"
        assert feed.last_build_date == "2024-01-01T00:00:00Z"
        assert feed.generator == "TestGenerator"
        assert len(feed.entries) == 1

        # Entry
        assert feed.entries[0].title == "First Entry"
        assert feed.entries[0].link == "https://example.com/first"
        assert feed.entries[0].description == "First entry summary"
        assert feed.entries[0].content == "First entry content"
        assert feed.entries[0].pub_date == "2024-01-01T00:00:00Z"
        assert feed.entries[0].author == "Test Author"
        assert feed.entries[0].guid == "urn:uuid:12345"
        assert feed.entries[0].categories == ["python", "testing"]

    def test_relative_url_resolution(self):
        """Test that relative URLs are resolved."""
        rss_xml = """<?xml version="1.0" encoding="UTF-8"?>
        <rss version="2.0">
          <channel>
            <title>Test Feed</title>
            <link>/feed</link>
            <item>
              <title>Item</title>
              <link>/item</link>
              <description>Test</description>
            </item>
          </channel>
        </rss>
        """
        parser = RSSParser(base_url="https://example.com/sub/")
        feed = parser.parse(rss_xml)
        assert feed.link == "https://example.com/feed"
        assert feed.entries[0].link == "https://example.com/item"

    def test_empty_feed(self):
        """Test parsing empty feed."""
        parser = RSSParser()
        feed = parser.parse("")
        # Empty content may default to rss type, but should have no entries
        assert feed.title == ""
        assert feed.entries == []

    def test_invalid_xml(self):
        """Test parsing invalid XML (should not crash)."""
        parser = RSSParser()
        feed = parser.parse("<rss><channel><title>Unclosed")
        assert isinstance(feed, Feed)

    def test_feed_with_media_thumbnail(self):
        """Test parsing feed with media:thumbnail."""
        rss_xml = """<?xml version="1.0" encoding="UTF-8"?>
        <rss version="2.0" xmlns:media="http://search.yahoo.com/mrss/">
          <channel>
            <title>Test Feed</title>
            <link>https://example.com</link>
            <description>Test</description>
            <item>
              <title>Item with image</title>
              <link>https://example.com/item</link>
              <description>Test</description>
              <media:thumbnail url="https://example.com/thumb.jpg" width="100" height="100"/>
            </item>
          </channel>
        </rss>
        """
        parser = RSSParser()
        feed = parser.parse(rss_xml)
        assert len(feed.entries) == 1
        assert feed.entries[0].image == "https://example.com/thumb.jpg"


class TestParseFeedFunction:
    """Tests for parse_feed convenience function."""

    def test_parse_feed_function(self):
        """Test the convenience function."""
        rss_xml = """<?xml version="1.0" encoding="UTF-8"?>
        <rss version="2.0">
          <channel>
            <title>Test Feed</title>
            <link>https://example.com</link>
            <description>Test</description>
            <item>
              <title>Item</title>
              <link>https://example.com/item</link>
              <description>Test</description>
            </item>
          </channel>
        </rss>
        """
        feed = parse_feed(rss_xml, base_url="https://example.com")
        assert feed.title == "Test Feed"
        assert len(feed.entries) == 1
        assert isinstance(feed, Feed)
