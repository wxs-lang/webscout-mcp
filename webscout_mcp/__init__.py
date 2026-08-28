"""webscout-mcp: A smart web search & fetch MCP server."""

__version__ = "0.5.0"

__all__ = [
    "__version__",
    "create_server",
    "Config",
    "Fetcher",
    "SearchEngine",
    "Crawler",
    "DataExtractor",
    "MetadataExtractor",
    "PageMetadata",
    "extract_metadata",
    "RSSParser",
    "Feed",
    "FeedEntry",
    "parse_feed",
    "fetch_and_parse_feed",
    "RobotsChecker",
    "Cache",
    "Exporter",
    "SitemapParser",
    "IncrementalCrawler",
    "UserAgentRotator",
]

from .cache import Cache
from .config import Config
from .crawler import Crawler
from .exporter import Exporter
from .extractor import DataExtractor
from .fetcher import Fetcher
from .incremental import IncrementalCrawler
from .metadata_extractor import MetadataExtractor, PageMetadata, extract_metadata
from .robots import RobotsChecker
from .rss_parser import RSSParser, Feed, FeedEntry, parse_feed, fetch_and_parse_feed
from .search import SearchEngine
from .sitemap import SitemapParser
from .user_agent import UserAgentRotator

# Server is optional - requires mcp library
try:
    from .server import create_server
except ImportError:
    create_server = None  # type: ignore[assignment]
