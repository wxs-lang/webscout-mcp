"""webscout-mcp: A smart web search & fetch MCP server."""

__version__ = "0.5.0"

__all__ = [
    "Cache",
    "Config",
    "Crawler",
    "DataExtractor",
    "Exporter",
    "Feed",
    "FeedEntry",
    "Fetcher",
    "IncrementalCrawler",
    "MetadataExtractor",
    "PageMetadata",
    "RSSParser",
    "RobotsChecker",
    "SearchEngine",
    "SitemapParser",
    "UserAgentRotator",
    "__version__",
    "create_server",
    "extract_metadata",
    "fetch_and_parse_feed",
    "parse_feed",
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
from .rss_parser import Feed, FeedEntry, RSSParser, fetch_and_parse_feed, parse_feed
from .search import SearchEngine
from .sitemap import SitemapParser
from .user_agent import UserAgentRotator

# Server is optional - requires mcp library
try:
    from .server import create_server
except ImportError:
    create_server = None  # type: ignore[assignment]
