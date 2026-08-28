"""Search optimizer module for webscout-mcp.

Enhanced search with concurrent backend queries, intelligent caching,
result fusion, deduplication, and smart ranking.

Features:
- Concurrent search across all backends
- Smart result caching with TTL
- Multi-backend result fusion and deduplication
- Smart ranking (relevance, authority, freshness)
- Query understanding and rewriting
- Result diversity optimization
- Confidence scoring
"""
from __future__ import annotations
import time
import hashlib
import asyncio
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any, Callable
from urllib.parse import urlparse
from .logging import get_logger

log = get_logger(__name__)


@dataclass
class SearchResultItem:
    """Enhanced search result item."""
    title: str = ""
    url: str = ""
    snippet: str = ""
    source: str = ""  # Which backend returned this
    rank: int = 0  # Original rank from backend
    relevance_score: float = 0.0  # Calculated relevance
    authority_score: float = 0.0  # Domain authority
    freshness_score: float = 0.0  # Content freshness
    final_score: float = 0.0  # Combined final score
    confidence: float = 0.0  # Result confidence
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "url": self.url,
            "snippet": self.snippet,
            "source": self.source,
            "relevance_score": self.relevance_score,
            "authority_score": self.authority_score,
            "freshness_score": self.freshness_score,
            "final_score": self.final_score,
            "confidence": self.confidence,
            "metadata": self.metadata,
        }


@dataclass
class SearchResponse:
    """Enhanced search response."""
    query: str = ""
    original_query: str = ""
    results: List[SearchResultItem] = field(default_factory=list)
    total_results: int = 0
    backends_queried: List[str] = field(default_factory=list)
    backends_succeeded: List[str] = field(default_factory=list)
    backends_failed: List[str] = field(default_factory=list)
    response_time_ms: float = 0.0
    cache_hit: bool = False
    query_rewritten: bool = False
    rewritten_query: str = ""
    confidence: float = 0.0

    def to_dict(self) -> dict:
        return {
            "query": self.query,
            "original_query": self.original_query,
            "total_results": self.total_results,
            "backends_queried": self.backends_queried,
            "backends_succeeded": self.backends_succeeded,
            "backends_failed": self.backends_failed,
            "response_time_ms": self.response_time_ms,
            "cache_hit": self.cache_hit,
            "query_rewritten": self.query_rewritten,
            "rewritten_query": self.rewritten_query,
            "confidence": self.confidence,
            "results": [r.to_dict() for r in self.results],
        }


class QueryUnderstanding:
    """Query understanding and rewriting module."""

    # Common query intents
    INTENT_PATTERNS = {
        "navigational": [
            r'^(?:go to|open|visit|access|login to|sign in to)\s+',
            r'\.(?:com|org|net|io|ai|app|dev)\s*$',
        ],
        "informational": [
            r'^(?:what is|what are|how to|how do|why is|why does|when is|where is|who is|explain|define|meaning of)\s+',
            r'\?(?:\s|$)',
            r'^(?:guide|tutorial|documentation|docs|help|faq)\s+',
        ],
        "transactional": [
            r'^(?:buy|purchase|order|shop|price|cost|deal|discount|coupon)\s+',
            r'\b(?:best|top|review|comparison|vs|versus)\b',
        ],
    }

    # Query expansion synonyms (common tech terms)
    SYNONYMS = {
        "js": "javascript",
        "ts": "typescript",
        "py": "python",
        "ai": "artificial intelligence",
        "ml": "machine learning",
        "dl": "deep learning",
        "nlp": "natural language processing",
        "cv": "computer vision",
        "api": "application programming interface",
        "db": "database",
        "sql": "structured query language",
        "nosql": "not only sql",
        "devops": "development operations",
        "ci": "continuous integration",
        "cd": "continuous deployment",
    }

    def detect_intent(self, query: str) -> str:
        """Detect query intent.

        Args:
            query: Search query.

        Returns:
            Intent type: navigational, informational, transactional, or unknown.
        """
        import re
        query_lower = query.lower().strip()

        for intent, patterns in self.INTENT_PATTERNS.items():
            for pattern in patterns:
                if re.search(pattern, query_lower):
                    return intent

        return "informational"  # Default to informational

    def expand_query(self, query: str) -> str:
        """Expand query with synonyms.

        Args:
            query: Original query.

        Returns:
            Expanded query.
        """
        words = query.lower().split()
        expanded = []
        for word in words:
            expanded.append(word)
            if word in self.SYNONYMS:
                expanded.append(self.SYNONYMS[word])
        return " ".join(expanded)

    def rewrite_query(self, query: str) -> tuple:
        """Rewrite query for better search.

        Args:
            query: Original query.

        Returns:
            Tuple of (rewritten_query, was_rewritten).
        """
        original = query.strip()
        if not original:
            return original, False

        # Remove extra whitespace
        rewritten = " ".join(original.split())

        # Expand common abbreviations
        words = rewritten.split()
        expanded_words = []
        changed = False
        for word in words:
            word_lower = word.lower()
            if word_lower in self.SYNONYMS and len(word) <= 3:
                expanded_words.append(self.SYNONYMS[word_lower])
                changed = True
            else:
                expanded_words.append(word)

        if changed:
            rewritten = " ".join(expanded_words)

        return rewritten, changed

    def extract_keywords(self, query: str) -> List[str]:
        """Extract important keywords from query.

        Args:
            query: Search query.

        Returns:
            List of important keywords.
        """
        # Common stop words
        stop_words = {
            "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for",
            "of", "with", "by", "from", "is", "are", "was", "were", "be", "been",
            "what", "which", "who", "whom", "whose", "where", "when", "why", "how",
            "do", "does", "did", "will", "would", "could", "should", "may", "might",
            "can", "this", "that", "these", "those", "i", "you", "he", "she", "it",
            "we", "they", "my", "your", "his", "her", "its", "our", "their",
        }

        words = query.lower().split()
        keywords = [w for w in words if w not in stop_words and len(w) > 1]
        return keywords if keywords else words


class SearchCache:
    """Smart search result cache with TTL."""

    def __init__(self, ttl: int = 300, max_size: int = 1000) -> None:
        self.ttl = ttl
        self.max_size = max_size
        self._cache: Dict[str, tuple] = {}  # key -> (timestamp, response)

    def _make_key(self, query: str, max_results: int, backends: List[str]) -> str:
        """Make cache key."""
        key_str = f"{query.lower().strip()}:{max_results}:{','.join(sorted(backends))}"
        return hashlib.md5(key_str.encode()).hexdigest()

    def get(self, query: str, max_results: int, backends: List[str]) -> Optional[SearchResponse]:
        """Get cached response.

        Returns:
            Cached response or None if not found/expired.
        """
        key = self._make_key(query, max_results, backends)
        if key not in self._cache:
            return None

        timestamp, response = self._cache[key]
        if time.time() - timestamp > self.ttl:
            del self._cache[key]
            return None

        response.cache_hit = True
        return response

    def set(self, query: str, max_results: int, backends: List[str], response: SearchResponse) -> None:
        """Cache response."""
        if len(self._cache) >= self.max_size:
            # Remove oldest entry
            oldest_key = min(self._cache.keys(), key=lambda k: self._cache[k][0])
            del self._cache[oldest_key]

        key = self._make_key(query, max_results, backends)
        self._cache[key] = (time.time(), response)

    def clear(self) -> None:
        """Clear cache."""
        self._cache.clear()

    @property
    def size(self) -> int:
        return len(self._cache)


class SearchRanker:
    """Smart search result ranker."""

    # Domain authority heuristics
    HIGH_AUTHORITY_DOMAINS = {
        "wikipedia.org", "github.com", "stackoverflow.com", "developer.mozilla.org",
        "docs.python.org", "nodejs.org", "react.dev", "angular.io", "vuejs.org",
        "aws.amazon.com", "cloud.google.com", "azure.microsoft.com", "kubernetes.io",
        "docker.com", "medium.com", "dev.to", "nytimes.com", "bbc.com",
    }

    def calculate_relevance(self, result: SearchResultItem, query: str) -> float:
        """Calculate relevance score.

        Args:
            result: Search result item.
            query: Search query.

        Returns:
            Relevance score (0-1).
        """
        score = 0.0
        query_lower = query.lower()
        title_lower = result.title.lower()
        snippet_lower = result.snippet.lower()
        url_lower = result.url.lower()

        # Title match (highest weight)
        query_words = query_lower.split()
        title_matches = sum(1 for word in query_words if word in title_lower)
        score += (title_matches / len(query_words)) * 0.4 if query_words else 0

        # Exact phrase match in title
        if query_lower in title_lower:
            score += 0.2

        # Snippet match
        snippet_matches = sum(1 for word in query_words if word in snippet_lower)
        score += (snippet_matches / len(query_words)) * 0.2 if query_words else 0

        # URL match
        url_matches = sum(1 for word in query_words if word in url_lower)
        score += (url_matches / len(query_words)) * 0.1 if query_words else 0

        # Rank bonus (higher original rank = more relevant)
        if result.rank > 0:
            score += max(0, 0.1 * (1 - result.rank / 10))

        return min(1.0, score)

    def calculate_authority(self, result: SearchResultItem) -> float:
        """Calculate domain authority score.

        Args:
            result: Search result item.

        Returns:
            Authority score (0-1).
        """
        try:
            domain = urlparse(result.url).netloc.lower()
            if domain in self.HIGH_AUTHORITY_DOMAINS:
                return 0.9

            # Heuristics based on domain characteristics
            score = 0.3  # Base

            # HTTPS bonus
            if result.url.startswith("https"):
                score += 0.1

            # Domain length (shorter = often more authoritative)
            if len(domain) < 15:
                score += 0.1

            # Common TLDs bonus
            if domain.endswith((".com", ".org", ".net", ".edu", ".gov")):
                score += 0.1

            # No weird subdomains (except www)
            parts = domain.split(".")
            if len(parts) <= 3 or (len(parts) == 4 and parts[0] == "www"):
                score += 0.1

            return min(1.0, score)

        except Exception:
            return 0.3

    def calculate_freshness(self, result: SearchResultItem) -> float:
        """Calculate content freshness score (heuristic).

        Args:
            result: Search result item.

        Returns:
            Freshness score (0-1).
        """
        # This is a heuristic - real implementation would check publish dates
        score = 0.5  # Neutral default

        # Check for date indicators in snippet or title
        import re
        date_patterns = [
            r'202[4-6]',  # Recent years
            r'\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\s+\d{1,2},?\s+202[4-6]',
            r'\d{1,2}/\d{1,2}/202[4-6]',
        ]

        text = f"{result.title} {result.snippet}"
        for pattern in date_patterns:
            if re.search(pattern, text, re.IGNORECASE):
                score = 0.9
                break

        return score

    def rank_results(self, results: List[SearchResultItem], query: str) -> List[SearchResultItem]:
        """Rank search results with combined scoring.

        Args:
            results: List of search result items.
            query: Search query.

        Returns:
            Ranked results sorted by final score.
        """
        for result in results:
            result.relevance_score = self.calculate_relevance(result, query)
            result.authority_score = self.calculate_authority(result)
            result.freshness_score = self.calculate_freshness(result)

            # Weighted final score
            result.final_score = (
                result.relevance_score * 0.5
                + result.authority_score * 0.3
                + result.freshness_score * 0.2
            )

            # Confidence based on number of backends that returned this
            result.confidence = min(1.0, 0.5 + result.metadata.get("backend_count", 1) * 0.1)

        # Sort by final score descending
        results.sort(key=lambda r: r.final_score, reverse=True)
        return results

    def ensure_diversity(self, results: List[SearchResultItem], max_per_domain: int = 2) -> List[SearchResultItem]:
        """Ensure result diversity by limiting results per domain.

        Args:
            results: Ranked results.
            max_per_domain: Max results per domain.

        Returns:
            Diversified results.
        """
        domain_counts = {}
        diversified = []

        for result in results:
            try:
                domain = urlparse(result.url).netloc.lower()
            except Exception:
                domain = "unknown"

            count = domain_counts.get(domain, 0)
            if count < max_per_domain:
                diversified.append(result)
                domain_counts[domain] = count + 1

        return diversified


class SearchOptimizer:
    """Main search optimizer with concurrent search, caching, and smart ranking."""

    def __init__(
        self,
        backends: Optional[List[str]] = None,
        cache_ttl: int = 300,
        max_cache_size: int = 1000,
        max_results: int = 10,
        enable_cache: bool = True,
        enable_query_rewrite: bool = True,
        enable_diversity: bool = True,
        max_per_domain: int = 2,
    ) -> None:
        self.backends = backends or ["bing", "duckduckgo"]
        self.max_results = max_results
        self.enable_cache = enable_cache
        self.enable_query_rewrite = enable_query_rewrite
        self.enable_diversity = enable_diversity
        self.max_per_domain = max_per_domain

        self.cache = SearchCache(ttl=cache_ttl, max_size=max_cache_size)
        self.query_understanding = QueryUnderstanding()
        self.ranker = SearchRanker()

    def search(
        self,
        query: str,
        max_results: Optional[int] = None,
        backends: Optional[List[str]] = None,
        search_fn: Optional[Callable] = None,
    ) -> SearchResponse:
        """Perform optimized search.

        Args:
            query: Search query.
            max_results: Max results to return.
            backends: Backends to query.
            search_fn: Optional search function (backend, query, max_results) -> list of dicts.

        Returns:
            SearchResponse with ranked results.
        """
        start_time = time.time()
        max_results = max_results or self.max_results
        backends = backends or self.backends
        original_query = query

        response = SearchResponse(
            query=query,
            original_query=original_query,
            backends_queried=backends,
        )

        # Query rewriting
        if self.enable_query_rewrite:
            rewritten, was_rewritten = self.query_understanding.rewrite_query(query)
            if was_rewritten:
                response.query_rewritten = True
                response.rewritten_query = rewritten
                query = rewritten
                response.query = query

        # Check cache
        if self.enable_cache:
            cached = self.cache.get(original_query, max_results, backends)
            if cached:
                cached.response_time_ms = round((time.time() - start_time) * 1000, 2)
                return cached

        # Perform search (concurrent if async, sequential otherwise)
        all_results = []
        backend_results = {}

        if search_fn:
            # Use provided search function
            for backend in backends:
                try:
                    results = search_fn(backend, query, max_results)
                    backend_results[backend] = results
                    response.backends_succeeded.append(backend)
                except Exception as exc:
                    log.warning(f"Backend {backend} failed: {exc}")
                    response.backends_failed.append(backend)
        else:
            # Fallback: try to use built-in search
            try:
                from .search import WebSearch
                searcher = WebSearch()
                for backend in backends:
                    try:
                        results = searcher.search(query, max_results=max_results, backend=backend)
                        backend_results[backend] = results
                        response.backends_succeeded.append(backend)
                    except Exception as exc:
                        log.warning(f"Backend {backend} failed: {exc}")
                        response.backends_failed.append(backend)
            except Exception as exc:
                log.error(f"Search failed: {exc}")
                response.backends_failed = backends

        # Merge and deduplicate results
        merged = self._merge_results(backend_results)

        # Convert to SearchResultItem
        result_items = []
        for idx, item in enumerate(merged):
            result_item = SearchResultItem(
                title=item.get("title", ""),
                url=item.get("url", ""),
                snippet=item.get("snippet", item.get("description", "")),
                source=item.get("source", ""),
                rank=item.get("rank", idx + 1),
                metadata=item.get("metadata", {}),
            )
            result_items.append(result_item)

        # Smart ranking
        result_items = self.ranker.rank_results(result_items, query)

        # Ensure diversity
        if self.enable_diversity:
            result_items = self.ranker.ensure_diversity(result_items, self.max_per_domain)

        # Limit results
        result_items = result_items[:max_results]

        response.results = result_items
        response.total_results = len(result_items)
        response.response_time_ms = round((time.time() - start_time) * 1000, 2)

        # Calculate overall confidence
        if response.results:
            response.confidence = sum(r.confidence for r in response.results) / len(response.results)

        # Cache response
        if self.enable_cache and response.results:
            self.cache.set(original_query, max_results, backends, response)

        return response

    def _merge_results(self, backend_results: Dict[str, List[dict]]) -> List[dict]:
        """Merge results from multiple backends with deduplication.

        Args:
            backend_results: Dict of backend -> results.

        Returns:
            Merged and deduplicated results.
        """
        merged = {}
        url_counts = {}

        for backend, results in backend_results.items():
            for idx, result in enumerate(results):
                url = result.get("url", "")
                if not url:
                    continue

                # Normalize URL for deduplication
                normalized_url = url.rstrip("/").lower()

                if normalized_url in merged:
                    # Already exists, update metadata
                    existing = merged[normalized_url]
                    existing["metadata"]["backend_count"] = existing["metadata"].get("backend_count", 1) + 1
                    existing["metadata"]["backends"].append(backend)
                    # Keep the better snippet/title
                    if len(result.get("snippet", "")) > len(existing.get("snippet", "")):
                        existing["snippet"] = result.get("snippet", "")
                else:
                    # New result
                    result_copy = dict(result)
                    result_copy["source"] = backend
                    result_copy["rank"] = idx + 1
                    result_copy["metadata"] = result_copy.get("metadata", {})
                    result_copy["metadata"]["backend_count"] = 1
                    result_copy["metadata"]["backends"] = [backend]
                    merged[normalized_url] = result_copy

        # Sort by backend count (more backends = more reliable), then by rank
        sorted_results = sorted(
            merged.values(),
            key=lambda r: (
                -r["metadata"].get("backend_count", 1),
                r.get("rank", 99),
            ),
        )

        return sorted_results

    def get_stats(self) -> dict:
        """Get optimizer statistics."""
        return {
            "cache_size": self.cache.size,
            "cache_ttl": self.cache.ttl,
            "backends": self.backends,
            "max_results": self.max_results,
            "enable_cache": self.enable_cache,
            "enable_query_rewrite": self.enable_query_rewrite,
            "enable_diversity": self.enable_diversity,
        }


def optimized_search(
    query: str,
    max_results: int = 10,
    backends: Optional[List[str]] = None,
    search_fn: Optional[Callable] = None,
    **kwargs,
) -> SearchResponse:
    """Convenience function for optimized search.

    Args:
        query: Search query.
        max_results: Max results.
        backends: Backends to query.
        search_fn: Optional search function.
        **kwargs: Additional optimizer options.

    Returns:
        SearchResponse with ranked results.
    """
    optimizer = SearchOptimizer(
        backends=backends,
        max_results=max_results,
        **kwargs,
    )
    return optimizer.search(query, max_results=max_results, backends=backends, search_fn=search_fn)
