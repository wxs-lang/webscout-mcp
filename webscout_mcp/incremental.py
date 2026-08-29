"""Incremental crawler with conditional requests (ETag/Last-Modified).

Only re-fetches pages that have changed since the last crawl, using HTTP
conditional headers (If-None-Match, If-Modified-Since).
"""

from __future__ import annotations

import asyncio
import json
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from .config import Config
from .fetcher import Fetcher, FetchResult
from .logging_config import get_logger
from .utils import normalize_url

log = get_logger(__name__)


@dataclass
class PageState:
    url: str
    etag: str = ""
    last_modified: str = ""
    content_hash: str = ""
    last_fetched: str = ""
    status_code: int = 0
    changed: bool = True


@dataclass
class IncrementalCrawlResult:
    seed_url: str
    pages_crawled: int = 0
    pages_changed: int = 0
    pages_unchanged: int = 0
    pages: list[FetchResult] = field(default_factory=list)
    errors: list[dict] = field(default_factory=list)
    state_file: str = ""

    def to_dict(self) -> dict:
        return {
            "seed_url": self.seed_url,
            "pages_crawled": self.pages_crawled,
            "pages_changed": self.pages_changed,
            "pages_unchanged": self.pages_unchanged,
            "pages": [p.to_dict() for p in self.pages],
            "errors": self.errors,
            "state_file": self.state_file,
        }


class IncrementalCrawler:
    """Crawler that only re-fetches changed pages using conditional requests."""

    def __init__(self, config: Config, fetcher: Fetcher, state_dir: Path | None = None) -> None:
        self.config = config
        self.fetcher = fetcher
        self.state_dir = state_dir or (config.cache_dir / "incremental")
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            client_kwargs: dict = {
                "timeout": httpx.Timeout(self.config.request_timeout),
                "follow_redirects": True,
                "headers": {"User-Agent": self.config.user_agent},
                "max_redirects": 5,
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

    def _state_file(self, seed_url: str) -> Path:
        parsed = urlparse(seed_url)
        safe_name = parsed.netloc.replace(":", "_").replace("/", "_")
        return self.state_dir / f"{safe_name}.json"

    def _load_state(self, seed_url: str) -> dict[str, PageState]:
        state_file = self._state_file(seed_url)
        if not state_file.exists():
            return {}
        try:
            with open(state_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            return {url: PageState(**state) for url, state in data.items()}
        except (json.JSONDecodeError, TypeError, KeyError):
            return {}

    def _save_state(self, seed_url: str, states: dict[str, PageState]) -> None:
        state_file = self._state_file(seed_url)
        data = {url: state.__dict__ for url, state in states.items()}
        with open(state_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    async def _conditional_fetch(self, url: str, state: PageState | None) -> tuple[FetchResult, PageState]:
        url = normalize_url(url)
        headers: dict[str, str] = {}
        if state:
            if state.etag:
                headers["If-None-Match"] = state.etag
            if state.last_modified:
                headers["If-Modified-Since"] = state.last_modified
        try:
            client = await self._get_client()
            response = await client.get(url, headers=headers)
            if response.status_code == 304 and state:
                result = FetchResult(url=url, final_url=str(response.url), status_code=304, cached=True)
                state.changed = False
                state.last_fetched = datetime.now(timezone.utc).isoformat()
                return result, state
            etag = response.headers.get("etag", "")
            last_modified = response.headers.get("last-modified", "")
            content = response.text
            new_state = PageState(
                url=url,
                etag=etag,
                last_modified=last_modified,
                content_hash=str(hash(content)),
                last_fetched=datetime.now(timezone.utc).isoformat(),
                status_code=response.status_code,
                changed=True,
            )
            title = ""
            try:
                soup = BeautifulSoup(content, "lxml")
                if soup.title and soup.title.string:
                    title = soup.title.string.strip()
            except Exception:
                pass
            result = FetchResult(
                url=url,
                final_url=str(response.url),
                status_code=response.status_code,
                title=title,
                content=content,
                content_type=response.headers.get("content-type", ""),
                raw_html=content,
                metadata={"encoding": response.encoding, "headers": dict(response.headers)},
            )
            return result, new_state
        except Exception as exc:
            result = FetchResult(url=url, final_url=url, status_code=0, error=f"{type(exc).__name__}: {exc}")
            new_state = state or PageState(url=url)
            new_state.changed = False
            return result, new_state

    async def crawl(self, seed_url: str, max_pages: int | None = None, extract: bool = True) -> IncrementalCrawlResult:
        seed_url = normalize_url(seed_url)
        page_limit = max_pages or self.config.crawler_max_pages
        state_file = self._state_file(seed_url)
        saved_states = self._load_state(seed_url)
        result = IncrementalCrawlResult(seed_url=seed_url, state_file=str(state_file))
        visited: set[str] = set()
        queue: deque[str] = deque([seed_url])
        seed_domain = urlparse(seed_url).netloc.lower()
        while queue and result.pages_crawled < page_limit:
            url = queue.popleft()
            if url in visited:
                continue
            visited.add(url)
            state = saved_states.get(url)
            fetch_result, new_state = await self._conditional_fetch(url, state)
            saved_states[url] = new_state
            if fetch_result.error:
                result.errors.append({"url": url, "error": fetch_result.error})
                continue
            result.pages_crawled += 1
            if fetch_result.status_code == 304:
                result.pages_unchanged += 1
                continue
            result.pages_changed += 1
            if extract and fetch_result.raw_html:
                extracted = await asyncio.to_thread(self.fetcher._extract_content, fetch_result.raw_html, "markdown")
                if extracted:
                    fetch_result.content = extracted
                    fetch_result.extracted = True
            result.pages.append(fetch_result)
            if fetch_result.raw_html and result.pages_crawled < page_limit:
                try:
                    soup = BeautifulSoup(fetch_result.raw_html, "lxml")
                    for a in soup.find_all("a", href=True):
                        href = a["href"].strip()
                        if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
                            continue
                        absolute = urljoin(url, href)
                        parsed = urlparse(absolute)
                        if parsed.scheme in ("http", "https") and parsed.netloc.lower() == seed_domain:
                            queue.append(normalize_url(absolute))
                except Exception:
                    pass
        self._save_state(seed_url, saved_states)
        log.info(
            "incremental crawl complete",
            seed=seed_url,
            pages=result.pages_crawled,
            changed=result.pages_changed,
            unchanged=result.pages_unchanged,
        )
        return result

    def clear_state(self, seed_url: str) -> None:
        state_file = self._state_file(seed_url)
        if state_file.exists():
            state_file.unlink()
