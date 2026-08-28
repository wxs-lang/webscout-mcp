"""Built-in plugins for webscout-mcp.

Provides example plugins demonstrating the plugin system:
- Search backend plugins
- Extractor plugins
- Alert channel plugins
- Post-processor plugins
"""

from __future__ import annotations

from typing import Any

from .plugin_system import (
    AlertChannelPlugin,
    ExtractorPlugin,
    Plugin,
    PostProcessorPlugin,
    SearchBackendPlugin,
    register_plugin,
)


@register_plugin
class ExampleSearchBackend(SearchBackendPlugin):
    """Example search backend plugin.

    Demonstrates how to create a custom search backend.
    """

    @property
    def name(self) -> str:
        return "example_search"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def description(self) -> str:
        return "Example search backend plugin for demonstration"

    @property
    def author(self) -> str:
        return "webscout-mcp"

    def initialize(self, config: dict = None) -> bool:
        self.api_key = (config or {}).get("api_key", "")
        return True

    def search(self, query: str, max_results: int = 10, **kwargs) -> list[dict]:
        """Example search implementation.

        In a real plugin, this would call a search API.
        """
        # This is just an example - return mock results
        return [
            {
                "title": f"Example result for: {query}",
                "url": f"https://example.com/search?q={query}",
                "snippet": f"This is an example search result for '{query}'.",
                "source": "example_search",
            }
        ][:max_results]


@register_plugin
class ReadabilityExtractor(ExtractorPlugin):
    """Readability-based content extractor plugin.

    Extracts main article content using readability-lxml.
    """

    @property
    def name(self) -> str:
        return "readability_extractor"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def description(self) -> str:
        return "Extracts main article content using readability-lxml"

    @property
    def author(self) -> str:
        return "webscout-mcp"

    def extract(self, html: str, url: str = "", **kwargs) -> dict:
        """Extract content using readability."""
        try:
            from readability import Document

            doc = Document(html)
            title = doc.title()
            content_html = doc.summary()

            # Convert HTML to text
            try:
                from bs4 import BeautifulSoup

                soup = BeautifulSoup(content_html, "html.parser")
                content_text = soup.get_text(separator="\n", strip=True)
            except ImportError:
                content_text = content_html

            return {
                "title": title,
                "content": content_text,
                "content_html": content_html,
                "extractor": "readability",
                "success": True,
            }
        except Exception as exc:
            return {
                "title": "",
                "content": "",
                "extractor": "readability",
                "success": False,
                "error": str(exc),
            }


@register_plugin
class ConsoleAlertChannel(AlertChannelPlugin):
    """Console output alert channel plugin.

    Outputs alerts to the console (useful for debugging).
    """

    @property
    def name(self) -> str:
        return "console_alert"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def description(self) -> str:
        return "Outputs alerts to the console (for debugging)"

    @property
    def author(self) -> str:
        return "webscout-mcp"

    def initialize(self, config: dict = None) -> bool:
        self.verbose = (config or {}).get("verbose", False)
        return True

    def send_alert(self, title: str, content: str, **kwargs) -> bool:
        """Send alert to console."""
        print("\n" + "=" * 60)
        print(f"ALERT: {title}")
        print("=" * 60)
        print(content)
        if self.verbose and kwargs:
            print(f"\nMetadata: {kwargs}")
        print("=" * 60 + "\n")
        return True


@register_plugin
class ContentLengthFilter(PostProcessorPlugin):
    """Content length filter post-processor plugin.

    Filters out content that is too short or too long.
    """

    @property
    def name(self) -> str:
        return "content_length_filter"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def description(self) -> str:
        return "Filters content by length (min/max characters)"

    @property
    def author(self) -> str:
        return "webscout-mcp"

    def initialize(self, config: dict = None) -> bool:
        config = config or {}
        self.min_length = config.get("min_length", 100)
        self.max_length = config.get("max_length", 100000)
        return True

    def process(self, data: Any, **kwargs) -> Any:
        """Filter content by length.

        Args:
            data: Dictionary with 'content' field, or list of such dictionaries.

        Returns:
            Filtered data.
        """
        if isinstance(data, dict):
            content = data.get("content", "")
            if self.min_length <= len(content) <= self.max_length:
                return data
            return None

        if isinstance(data, list):
            return [
                item
                for item in data
                if isinstance(item, dict) and self.min_length <= len(item.get("content", "")) <= self.max_length
            ]

        return data


@register_plugin
class LanguageDetector(PostProcessorPlugin):
    """Language detection post-processor plugin.

    Detects the language of text content.
    """

    @property
    def name(self) -> str:
        return "language_detector"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def description(self) -> str:
        return "Detects the language of text content"

    @property
    def author(self) -> str:
        return "webscout-mcp"

    def initialize(self, config: dict = None) -> bool:
        self.use_langdetect = (config or {}).get("use_langdetect", False)
        return True

    def process(self, data: Any, **kwargs) -> Any:
        """Detect language of content.

        Args:
            data: Dictionary with 'content' field.

        Returns:
            Data with added 'language' field.
        """
        if not isinstance(data, dict):
            return data

        content = data.get("content", "")
        if not content:
            data["language"] = "unknown"
            return data

        # Simple heuristic-based detection
        language = self._detect_language(content)
        data["language"] = language
        return data

    def _detect_language(self, text: str) -> str:
        """Simple language detection based on character analysis."""
        # Count Chinese characters
        chinese_chars = sum(1 for c in text if "\u4e00" <= c <= "\u9fff")
        # Count Japanese characters
        japanese_chars = sum(1 for c in text if "\u3040" <= c <= "\u30ff")
        # Count Korean characters
        korean_chars = sum(1 for c in text if "\uac00" <= c <= "\ud7af")
        # Count Cyrillic characters
        cyrillic_chars = sum(1 for c in text if "\u0400" <= c <= "\u04ff")

        total_chars = len(text)
        if total_chars == 0:
            return "unknown"

        # Determine dominant language
        if chinese_chars / total_chars > 0.1:
            return "zh"
        elif japanese_chars / total_chars > 0.1:
            return "ja"
        elif korean_chars / total_chars > 0.1:
            return "ko"
        elif cyrillic_chars / total_chars > 0.1:
            return "ru"
        else:
            return "en"


@register_plugin
class DuplicateRemover(PostProcessorPlugin):
    """Duplicate content remover post-processor plugin.

    Removes duplicate content based on content hash.
    """

    @property
    def name(self) -> str:
        return "duplicate_remover"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def description(self) -> str:
        return "Removes duplicate content based on content hash"

    @property
    def author(self) -> str:
        return "webscout-mcp"

    def initialize(self, config: dict = None) -> bool:
        self._seen_hashes = set()
        return True

    def process(self, data: Any, **kwargs) -> Any:
        """Remove duplicates.

        Args:
            data: List of dictionaries with 'content' field.

        Returns:
            List with duplicates removed.
        """
        if not isinstance(data, list):
            return data

        import hashlib

        unique_items = []
        for item in data:
            if not isinstance(item, dict):
                unique_items.append(item)
                continue

            content = item.get("content", "")
            content_hash = hashlib.md5(content.encode()).hexdigest()

            if content_hash not in self._seen_hashes:
                self._seen_hashes.add(content_hash)
                unique_items.append(item)

        return unique_items

    def cleanup(self) -> None:
        """Clear seen hashes."""
        self._seen_hashes.clear()
