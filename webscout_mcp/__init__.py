"""webscout-mcp: A smart web search & fetch MCP server."""

__version__ = "0.4.0"

__all__ = [
    "__version__",
    "create_server",
    "Config",
    "Fetcher",
    "SearchEngine",
    "Crawler",
    "DataExtractor",
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
from .robots import RobotsChecker
from .search import SearchEngine
from .sitemap import SitemapParser
from .user_agent import UserAgentRotator

# Server is optional - requires mcp library
try:
    from .server import create_server
except ImportError:
    create_server = None  # type: ignore[assignment]
