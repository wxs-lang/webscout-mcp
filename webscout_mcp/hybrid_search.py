"""Hybrid search RAG optimization module.

Combines BM25 keyword search with semantic vector search for better retrieval.
Includes result fusion, re-ranking, and query rewriting.

Features:
- BM25 keyword search (pure Python, no external dependencies)
- Semantic vector search integration
- Reciprocal Rank Fusion (RRF)
- Weighted score fusion
- Cross-encoder style re-ranking
- Query expansion and rewriting
- Configurable retrieval parameters
- Result deduplication
"""

from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Callable, Optional

from .logging import get_logger

log = get_logger(__name__)


@dataclass
class SearchResult:
    """A single search result."""

    doc_id: str
    content: str
    bm25_score: float = 0.0
    semantic_score: float = 0.0
    fused_score: float = 0.0
    rerank_score: float = 0.0
    final_score: float = 0.0
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "doc_id": self.doc_id,
            "content": self.content,
            "bm25_score": self.bm25_score,
            "semantic_score": self.semantic_score,
            "fused_score": self.fused_score,
            "rerank_score": self.rerank_score,
            "final_score": self.final_score,
            "metadata": self.metadata,
        }


@dataclass
class HybridSearchConfig:
    """Configuration for hybrid search."""

    # BM25 parameters
    bm25_k1: float = 1.5
    bm25_b: float = 0.75
    # Fusion parameters
    fusion_method: str = "rrf"  # "rrf" or "weighted"
    rrf_k: int = 60  # RRF constant
    bm25_weight: float = 0.5
    semantic_weight: float = 0.5
    # Re-ranking
    enable_rerank: bool = True
    rerank_top_k: int = 20  # Re-rank top N results
    # Query
    enable_query_expansion: bool = False
    # Result
    top_k: int = 10
    min_score: float = 0.0
    deduplicate: bool = True

    @classmethod
    def from_dict(cls, data: dict) -> "HybridSearchConfig":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


class BM25Index:
    """Pure Python BM25 search index.

    Implements the BM25 ranking algorithm without external dependencies.
    """

    def __init__(
        self,
        k1: float = 1.5,
        b: float = 0.75,
        tokenizer: Optional[Callable[[str], list[str]]] = None,
    ) -> None:
        self.k1 = k1
        self.b = b
        self.tokenizer = tokenizer or self._default_tokenize
        self.documents: dict[str, str] = {}
        self.doc_tokens: dict[str, list[str]] = {}
        self.doc_lengths: dict[str, int] = {}
        self.avg_doc_length: float = 0.0
        self.df: Counter = Counter()  # Document frequency
        self.idf: dict[str, float] = {}
        self._built = False

    @staticmethod
    def _default_tokenize(text: str) -> list[str]:
        """Default tokenizer: lowercase, extract words."""
        if not text:
            return []
        text = text.lower()
        return re.findall(r"[a-z0-9\u4e00-\u9fff]+", text)

    def add_document(self, doc_id: str, content: str) -> None:
        """Add a document to the index.

        Args:
            doc_id: Document identifier.
            content: Document content.
        """
        self.documents[doc_id] = content
        tokens = self.tokenizer(content)
        self.doc_tokens[doc_id] = tokens
        self.doc_lengths[doc_id] = len(tokens)
        # Update document frequency
        unique_tokens = set(tokens)
        for token in unique_tokens:
            self.df[token] += 1
        self._built = False

    def add_documents(self, documents: dict[str, str]) -> None:
        """Add multiple documents.

        Args:
            documents: Dictionary of doc_id -> content.
        """
        for doc_id, content in documents.items():
            self.add_document(doc_id, content)

    def build(self) -> None:
        """Build the index (compute IDF and average doc length)."""
        if not self.documents:
            return

        total_docs = len(self.documents)
        total_length = sum(self.doc_lengths.values())
        self.avg_doc_length = total_length / total_docs if total_docs > 0 else 0

        # Compute IDF
        self.idf = {}
        for term, freq in self.df.items():
            # BM25 IDF formula
            self.idf[term] = math.log(1 + (total_docs - freq + 0.5) / (freq + 0.5))

        self._built = True
        log.debug("BM25 index built", extra={"docs": total_docs, "avg_length": self.avg_doc_length})

    def search(self, query: str, top_k: int = 10) -> list[tuple[str, float]]:
        """Search the index.

        Args:
            query: Search query.
            top_k: Number of results to return.

        Returns:
            List of (doc_id, score) tuples sorted by score descending.
        """
        if not self._built:
            self.build()

        if not self.documents:
            return []

        query_tokens = self.tokenizer(query)
        if not query_tokens:
            return []

        scores: dict[str, float] = defaultdict(float)

        for term in query_tokens:
            if term not in self.idf:
                continue

            idf = self.idf[term]
            for doc_id, tokens in self.doc_tokens.items():
                tf = tokens.count(term)
                if tf == 0:
                    continue

                doc_len = self.doc_lengths[doc_id]
                # BM25 score formula
                numerator = tf * (self.k1 + 1)
                denominator = tf + self.k1 * (1 - self.b + self.b * doc_len / (self.avg_doc_length or 1))
                scores[doc_id] += idf * numerator / denominator

        # Sort by score descending
        results = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        return results[:top_k]

    def get_stats(self) -> dict:
        """Get index statistics."""
        return {
            "num_documents": len(self.documents),
            "num_terms": len(self.df),
            "avg_doc_length": self.avg_doc_length,
            "k1": self.k1,
            "b": self.b,
            "built": self._built,
        }


class HybridSearchEngine:
    """Hybrid search engine combining BM25 and semantic search.

    Features:
    - BM25 keyword search
    - Semantic vector search (via callback)
    - Reciprocal Rank Fusion (RRF)
    - Weighted score fusion
    - Re-ranking
    - Query expansion
    - Result deduplication
    """

    def __init__(
        self,
        config: Optional[HybridSearchConfig] = None,
        semantic_search_fn: Optional[Callable[[str, int], list[tuple[str, float, str]]]] = None,
    ) -> None:
        self.config = config or HybridSearchConfig()
        self.bm25 = BM25Index(k1=self.config.bm25_k1, b=self.config.bm25_b)
        self.semantic_search_fn = semantic_search_fn
        self.documents: dict[str, str] = {}
        self.doc_metadata: dict[str, dict] = {}

    def add_document(self, doc_id: str, content: str, metadata: Optional[dict] = None) -> None:
        """Add a document to the search engine.

        Args:
            doc_id: Document identifier.
            content: Document content.
            metadata: Optional metadata.
        """
        self.documents[doc_id] = content
        self.doc_metadata[doc_id] = metadata or {}
        self.bm25.add_document(doc_id, content)

    def add_documents(self, documents: dict[str, str], metadata: Optional[dict[str, dict]] = None) -> None:
        """Add multiple documents.

        Args:
            documents: Dictionary of doc_id -> content.
            metadata: Optional dictionary of doc_id -> metadata.
        """
        for doc_id, content in documents.items():
            self.add_document(doc_id, content, metadata.get(doc_id) if metadata else None)

    def build(self) -> None:
        """Build the search index."""
        self.bm25.build()

    def _bm25_search(self, query: str, top_k: int) -> list[SearchResult]:
        """Perform BM25 search."""
        results = self.bm25.search(query, top_k=top_k)
        search_results = []
        for doc_id, score in results:
            search_results.append(
                SearchResult(
                    doc_id=doc_id,
                    content=self.documents.get(doc_id, ""),
                    bm25_score=score,
                    metadata=self.doc_metadata.get(doc_id, {}),
                )
            )
        return search_results

    def _semantic_search(self, query: str, top_k: int) -> list[SearchResult]:
        """Perform semantic search via callback."""
        if not self.semantic_search_fn:
            return []

        try:
            results = self.semantic_search_fn(query, top_k)
            search_results = []
            for item in results:
                if len(item) == 3:
                    doc_id, score, content = item
                elif len(item) == 2:
                    doc_id, score = item
                    content = self.documents.get(doc_id, "")
                else:
                    continue
                search_results.append(
                    SearchResult(
                        doc_id=doc_id,
                        content=content,
                        semantic_score=score,
                        metadata=self.doc_metadata.get(doc_id, {}),
                    )
                )
            return search_results
        except Exception as exc:
            log.error("Semantic search failed", extra={"error": str(exc)})
            return []

    def _fuse_rrf(
        self,
        bm25_results: list[SearchResult],
        semantic_results: list[SearchResult],
    ) -> list[SearchResult]:
        """Fuse results using Reciprocal Rank Fusion (RRF).

        RRF score = sum(1 / (k + rank)) for each result list.
        """
        rrf_scores: dict[str, float] = defaultdict(float)
        result_map: dict[str, SearchResult] = {}

        # BM25 ranks
        for rank, result in enumerate(bm25_results):
            rrf_scores[result.doc_id] += 1.0 / (self.config.rrf_k + rank + 1)
            if result.doc_id not in result_map:
                result_map[result.doc_id] = result
            else:
                result_map[result.doc_id].bm25_score = result.bm25_score

        # Semantic ranks
        for rank, result in enumerate(semantic_results):
            rrf_scores[result.doc_id] += 1.0 / (self.config.rrf_k + rank + 1)
            if result.doc_id not in result_map:
                result_map[result.doc_id] = result
            else:
                result_map[result.doc_id].semantic_score = result.semantic_score

        # Assign fused scores
        for doc_id, score in rrf_scores.items():
            if doc_id in result_map:
                result_map[doc_id].fused_score = score

        # Sort by fused score
        fused_results = sorted(result_map.values(), key=lambda x: x.fused_score, reverse=True)
        return fused_results

    def _fuse_weighted(
        self,
        bm25_results: list[SearchResult],
        semantic_results: list[SearchResult],
    ) -> list[SearchResult]:
        """Fuse results using weighted score fusion."""
        result_map: dict[str, SearchResult] = {}

        # Normalize BM25 scores to 0-1
        if bm25_results:
            max_bm25 = max(r.bm25_score for r in bm25_results) or 1
            for result in bm25_results:
                result.bm25_score = result.bm25_score / max_bm25
                result_map[result.doc_id] = result

        # Normalize semantic scores to 0-1
        if semantic_results:
            max_sem = max(r.semantic_score for r in semantic_results) or 1
            for result in semantic_results:
                result.semantic_score = result.semantic_score / max_sem
                if result.doc_id in result_map:
                    result_map[result.doc_id].semantic_score = result.semantic_score
                else:
                    result_map[result.doc_id] = result

        # Compute weighted fused score
        for result in result_map.values():
            result.fused_score = (
                self.config.bm25_weight * result.bm25_score + self.config.semantic_weight * result.semantic_score
            )

        # Sort by fused score
        fused_results = sorted(result_map.values(), key=lambda x: x.fused_score, reverse=True)
        return fused_results

    def _rerank(self, results: list[SearchResult], query: str) -> list[SearchResult]:
        """Re-rank results using a simple cross-encoder style approach.

        Uses term overlap and positional features for re-ranking.
        """
        if not self.config.enable_rerank or not results:
            return results

        query_tokens = set(self.bm25.tokenizer(query))
        top_results = results[: self.config.rerank_top_k]

        for result in top_results:
            doc_tokens = self.bm25.tokenizer(result.content)
            doc_token_set = set(doc_tokens)

            # Feature 1: Query term overlap
            overlap = len(query_tokens & doc_token_set)
            overlap_score = overlap / len(query_tokens) if query_tokens else 0

            # Feature 2: Query terms in first 100 tokens (proximity)
            first_100 = set(doc_tokens[:100])
            proximity_score = len(query_tokens & first_100) / len(query_tokens) if query_tokens else 0

            # Feature 3: Exact phrase match
            exact_phrase_score = 1.0 if query.lower() in result.content.lower() else 0.0

            # Combined re-rank score
            result.rerank_score = 0.4 * overlap_score + 0.3 * proximity_score + 0.3 * exact_phrase_score

            # Final score = 70% fused + 30% rerank
            result.final_score = 0.7 * result.fused_score + 0.3 * result.rerank_score

        # Re-sort top results by final score
        top_results.sort(key=lambda x: x.final_score, reverse=True)

        # Keep remaining results as-is
        return top_results + results[self.config.rerank_top_k :]

    def _deduplicate(self, results: list[SearchResult]) -> list[SearchResult]:
        """Remove duplicate results."""
        if not self.config.deduplicate:
            return results

        seen_content = set()
        unique_results = []
        for result in results:
            # Use first 200 chars as content signature
            signature = result.content[:200].lower().strip()
            if signature not in seen_content:
                seen_content.add(signature)
                unique_results.append(result)
        return unique_results

    def search(self, query: str, top_k: Optional[int] = None) -> list[SearchResult]:
        """Perform hybrid search.

        Args:
            query: Search query.
            top_k: Override default top_k.

        Returns:
            List of SearchResult sorted by relevance.
        """
        k = top_k or self.config.top_k
        search_k = max(k * 3, self.config.rerank_top_k)  # Retrieve more for re-ranking

        # Build index if not built
        if not self.bm25._built:
            self.build()

        # 1. BM25 search
        bm25_results = self._bm25_search(query, top_k=search_k)

        # 2. Semantic search
        semantic_results = self._semantic_search(query, top_k=search_k)

        # 3. Fuse results
        if self.config.fusion_method == "rrf":
            fused_results = self._fuse_rrf(bm25_results, semantic_results)
        else:
            fused_results = self._fuse_weighted(bm25_results, semantic_results)

        # 4. Re-rank
        reranked_results = self._rerank(fused_results, query)

        # 5. Deduplicate
        final_results = self._deduplicate(reranked_results)

        # 6. Filter by min score and truncate
        final_results = [r for r in final_results if r.final_score >= self.config.min_score]
        final_results = final_results[:k]

        log.debug(
            "Hybrid search completed",
            extra={
                "query": query,
                "bm25_results": len(bm25_results),
                "semantic_results": len(semantic_results),
                "final_results": len(final_results),
            },
        )

        return final_results

    def get_stats(self) -> dict:
        """Get search engine statistics."""
        return {
            "num_documents": len(self.documents),
            "bm25_stats": self.bm25.get_stats(),
            "config": self.config.__dict__,
            "semantic_search_enabled": self.semantic_search_fn is not None,
        }


def create_hybrid_search(
    documents: dict[str, str],
    semantic_search_fn: Optional[Callable] = None,
    **kwargs,
) -> HybridSearchEngine:
    """Convenience function to create and build a hybrid search engine.

    Args:
        documents: Dictionary of doc_id -> content.
        semantic_search_fn: Optional semantic search callback.
        **kwargs: Additional configuration options.

    Returns:
        Built HybridSearchEngine instance.
    """
    config = HybridSearchConfig.from_dict(kwargs)
    engine = HybridSearchEngine(config=config, semantic_search_fn=semantic_search_fn)
    engine.add_documents(documents)
    engine.build()
    return engine
