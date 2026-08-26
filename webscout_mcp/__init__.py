"""webscout-mcp: A smart web search & fetch MCP server."""

__version__ = "0.2.0"

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
]

from .cache import Cache
from .config import Config
from .crawler import Crawler
from .extractor import DataExtractor
from .fetcher import Fetcher
from .robots import RobotsChecker
from .search import SearchEngine
from .server import create_server
