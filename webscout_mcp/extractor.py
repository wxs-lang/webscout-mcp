"""Structured data extraction from HTML using CSS selectors.

Given a URL (or raw HTML) and a set of CSS selectors, extract structured
data into a JSON-serializable dictionary.  Supports single-value, list, and
attribute extraction.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from bs4 import BeautifulSoup

from .config import Config
from .fetcher import Fetcher


@dataclass
class ExtractionRule:
    """A single extraction rule.

    Attributes:
        name: The key in the output dictionary.
        selector: CSS selector (e.g. ``h1.title``, ``.price``).
        attribute: HTML attribute to extract (e.g. ``href``, ``src``).
            If None, extracts the element's text content.
        multiple: If True, return a list of all matches; otherwise return
            the first match only.
        regex: Optional regex to apply to the extracted text.
        default: Default value if nothing matches.
    """

    name: str
    selector: str
    attribute: str | None = None
    multiple: bool = False
    regex: str | None = None
    default: Any = None


class DataExtractor:
    """Extract structured data from web pages using CSS selectors."""

    def __init__(self, config: Config, fetcher: Fetcher):
        self.config = config
        self.fetcher = fetcher

    async def extract_from_url(
        self,
        url: str,
        rules: list[ExtractionRule],
    ) -> dict:
        """Fetch a URL and extract structured data.

        Args:
            url: The URL to fetch.
            rules: A list of extraction rules.

        Returns:
            A dictionary with extracted data, plus metadata.
        """
        page = await self.fetcher.fetch(url, extract=False, max_chars=200000)
        if page.error:
            return {"url": url, "error": page.error, "data": {}}

        data = self.extract_from_html(page.content, rules)
        return {
            "url": url,
            "final_url": page.final_url,
            "title": page.title,
            "data": data,
        }

    def extract_from_html(
        self,
        html: str,
        rules: list[ExtractionRule],
    ) -> dict:
        """Extract structured data from raw HTML.

        Args:
            html: Raw HTML content.
            rules: A list of extraction rules.

        Returns:
            A dictionary mapping rule names to extracted values.
        """
        soup = BeautifulSoup(html, "lxml")
        result: dict[str, Any] = {}

        for rule in rules:
            try:
                value = self._apply_rule(soup, rule)
                result[rule.name] = value
            except Exception as exc:
                result[rule.name] = {"error": f"{type(exc).__name__}: {exc}"}

        return result

    def _apply_rule(self, soup: BeautifulSoup, rule: ExtractionRule) -> Any:
        """Apply a single extraction rule to a BeautifulSoup object."""
        elements = soup.select(rule.selector)

        if not elements:
            return rule.default

        if rule.multiple:
            values = []
            for el in elements:
                val = self._extract_element_value(el, rule)
                if val is not None:
                    values.append(val)
            return values

        # Single value
        val = self._extract_element_value(elements[0], rule)
        return val if val is not None else rule.default

    def _extract_element_value(self, element, rule: ExtractionRule) -> str | None:
        """Extract the value from a single element."""
        if rule.attribute:
            val = element.get(rule.attribute)
        else:
            val = element.get_text(strip=True)

        if val is None:
            return None

        val = str(val).strip()

        if rule.regex:
            match = re.search(rule.regex, val)
            if match:
                # Return first capture group if present, else full match
                val = match.group(1) if match.groups() else match.group(0)
            else:
                return None

        return val
