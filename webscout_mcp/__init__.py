"""webscout-mcp: A smart web search & fetch MCP server."""

__version__ = "0.6.1"

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

# Lazy imports to reduce startup time
# These modules are only imported when actually accessed
_lazy_imports = {
    "Cache": (".cache", "Cache"),
    "Config": (".config", "Config"),
    "Crawler": (".crawler", "Crawler"),
    "DataExtractor": (".extractor", "DataExtractor"),
    "Exporter": (".exporter", "Exporter"),
    "Feed": (".rss_parser", "Feed"),
    "FeedEntry": (".rss_parser", "FeedEntry"),
    "Fetcher": (".fetcher", "Fetcher"),
    "IncrementalCrawler": (".incremental", "IncrementalCrawler"),
    "MetadataExtractor": (".metadata_extractor", "MetadataExtractor"),
    "PageMetadata": (".metadata_extractor", "PageMetadata"),
    "RSSParser": (".rss_parser", "RSSParser"),
    "RobotsChecker": (".robots", "RobotsChecker"),
    "SearchEngine": (".search", "SearchEngine"),
    "SitemapParser": (".sitemap", "SitemapParser"),
    "UserAgentRotator": (".user_agent", "UserAgentRotator"),
    "extract_metadata": (".metadata_extractor", "extract_metadata"),
    "fetch_and_parse_feed": (".rss_parser", "fetch_and_parse_feed"),
    "parse_feed": (".rss_parser", "parse_feed"),
}

_imported = {}


def __getattr__(name: str):
    """Lazy import modules only when accessed."""
    if name in _lazy_imports:
        if name not in _imported:
            module_name, attr_name = _lazy_imports[name]
            import importlib

            module = importlib.import_module(module_name, __name__)
            _imported[name] = getattr(module, attr_name)
        return _imported[name]
    if name == "create_server":
        if name not in _imported:
            try:
                from .server import create_server as _cs

                _imported[name] = _cs
            except ImportError:
                _imported[name] = None
        return _imported[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__():
    return list(__all__) + list(globals().keys())
