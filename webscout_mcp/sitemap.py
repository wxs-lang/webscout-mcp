"""Sitemap parser and fetcher.

Parses sitemap.xml and sitemap index files, extracts all URLs, and supports
incremental fetching with lastmod filtering.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
from urllib.parse import urljoin, urlparse
from xml.etree import ElementTree as ET

import httpx

from .config import Config
from .logging import get_logger
from .utils import normalize_url

log = get_logger(__name__)

_SITEMAP_NS = {
    "sm": "http://www.sitemaps.org/schemas/sitemap/0.9",
}


@dataclass
class SitemapEntry:
    url: str
    lastmod: Optional[datetime] = None
    changefreq: Optional[str] = None
    priority: Optional[float] = None


@dataclass
class SitemapResult:
    source_url: str
    urls: list[SitemapEntry] = field(default_factory=list)
    sub_sitemaps: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    is_index: bool = False

    @property
    def url_count(self) -> int:
        return len(self.urls)


class SitemapParser:
    """Parse and fetch sitemaps, with support for sitemap index files."""

    def __init__(self, config: Config) -> None:
        self.config = config
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            client_kwargs: dict = {
                "timeout": httpx.Timeout(self.config.request_timeout),
                "follow_redirects": True,
                "headers": {"User-Agent": self.config.user_agent},
            }
            proxies: dict[str, str] = {}
            if self.config.proxy_http:
                proxies["http://"] = self.config.proxy_http
            if self.config.proxy_https:
                proxies["https://"] = self.config.proxy_https
            if proxies:
                client_kwargs["proxies"] = proxies
            self._client = httpx.AsyncClient(**client_kwargs)
        return self._client

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    async def fetch_sitemap(self, url: str, recursive: bool = True) -> SitemapResult:
        url = normalize_url(url)
        result = SitemapResult(source_url=url)
        try:
            client = await self._get_client()
            response = await client.get(url)
            response.raise_for_status()
        except Exception as exc:
            result.errors.append(f"Failed to fetch sitemap: {type(exc).__name__}: {exc}")
            return result

        try:
            root = ET.fromstring(response.content)
        except ET.ParseError as exc:
            result.errors.append(f"Failed to parse sitemap XML: {exc}")
            return result

        if root.tag.endswith("sitemapindex"):
            result.is_index = True
            for sitemap_elem in root.findall("sm:sitemap", _SITEMAP_NS):
                loc_elem = sitemap_elem.find("sm:loc", _SITEMAP_NS)
                if loc_elem is not None and loc_elem.text:
                    result.sub_sitemaps.append(normalize_url(loc_elem.text.strip()))
            if recursive:
                for sub_url in result.sub_sitemaps:
                    sub_result = await self.fetch_sitemap(sub_url, recursive=True)
                    result.urls.extend(sub_result.urls)
                    result.errors.extend(sub_result.errors)
        else:
            for url_elem in root.findall("sm:url", _SITEMAP_NS):
                entry = self._parse_url_entry(url_elem)
                if entry:
                    result.urls.append(entry)

        log.info("sitemap parsed", url=url, url_count=result.url_count, is_index=result.is_index)
        return result

    @staticmethod
    def _parse_url_entry(url_elem: ET.Element) -> Optional[SitemapEntry]:
        loc_elem = url_elem.find("sm:loc", _SITEMAP_NS)
        if loc_elem is None or not loc_elem.text:
            return None
        url = normalize_url(loc_elem.text.strip())
        lastmod = None
        lastmod_elem = url_elem.find("sm:lastmod", _SITEMAP_NS)
        if lastmod_elem is not None and lastmod_elem.text:
            try:
                lastmod = datetime.fromisoformat(lastmod_elem.text.strip().replace("Z", "+00:00"))
            except (ValueError, TypeError):
                pass
        changefreq = None
        changefreq_elem = url_elem.find("sm:changefreq", _SITEMAP_NS)
        if changefreq_elem is not None and changefreq_elem.text:
            changefreq = changefreq_elem.text.strip()
        priority = None
        priority_elem = url_elem.find("sm:priority", _SITEMAP_NS)
        if priority_elem is not None and priority_elem.text:
            try:
                priority = float(priority_elem.text.strip())
            except (ValueError, TypeError):
                pass
        return SitemapEntry(url=url, lastmod=lastmod, changefreq=changefreq, priority=priority)

    async def discover_sitemaps(self, base_url: str) -> list[str]:
        parsed = urlparse(base_url)
        domain = f"{parsed.scheme}://{parsed.netloc}"
        candidates = [
            f"{domain}/sitemap.xml",
            f"{domain}/sitemap_index.xml",
            f"{domain}/sitemap-index.xml",
            f"{domain}/sitemap.php",
            f"{domain}/sitemap.txt",
        ]
        found: list[str] = []
        for url in candidates:
            try:
                client = await self._get_client()
                response = await client.head(url, follow_redirects=True)
                if response.status_code == 200:
                    found.append(url)
            except Exception:
                pass
        try:
            client = await self._get_client()
            response = await client.get(f"{domain}/robots.txt")
            if response.status_code == 200:
                for line in response.text.splitlines():
                    if line.lower().startswith("sitemap:"):
                        sitemap_url = line.split(":", 1)[1].strip()
                        if sitemap_url.startswith("http"):
                            found.append(sitemap_url)
                        else:
                            found.append(urljoin(domain, sitemap_url))
        except Exception:
            pass
        seen = set()
        unique = []
        for url in found:
            normalized = url.rstrip("/").lower()
            if normalized not in seen:
                seen.add(normalized)
                unique.append(url)
        return unique
