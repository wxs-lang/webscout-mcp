"""Tests for hybrid search RAG optimization module."""
import pytest
from webscout_mcp.hybrid_search import (
    SearchResult,
    HybridSearchConfig,
    BM25Index,
    HybridSearchEngine,
    create_hybrid_search,
)


class TestSearchResult:
    """Test SearchResult class."""

    def test_creation(self):
        result = SearchResult(doc_id="doc1", content="test content")
        assert result.doc_id == "doc1"
        assert result.content == "test content"
        assert result.bm25_score == 0.0
        assert result.final_score == 0.0

    def test_to_dict(self):
        result = SearchResult(
            doc_id="doc1",
            content="test",
            bm25_score=1.5,
            semantic_score=0.9,
            final_score=0.85,
            metadata={"source": "web"},
        )
        data = result.to_dict()
        assert data["doc_id"] == "doc1"
        assert data["bm25_score"] == 1.5
        assert data["semantic_score"] == 0.9
        assert data["final_score"] == 0.85
        assert data["metadata"]["source"] == "web"


class TestHybridSearchConfig:
    """Test HybridSearchConfig class."""

    def test_default_config(self):
        config = HybridSearchConfig()
        assert config.bm25_k1 == 1.5
        assert config.bm25_b == 0.75
        assert config.fusion_method == "rrf"
        assert config.rrf_k == 60
        assert config.bm25_weight == 0.5
        assert config.semantic_weight == 0.5
        assert config.enable_rerank is True
        assert config.top_k == 10

    def test_custom_config(self):
        config = HybridSearchConfig(
            bm25_k1=2.0,
            fusion_method="weighted",
            top_k=20,
            enable_rerank=False,
        )
        assert config.bm25_k1 == 2.0
        assert config.fusion_method == "weighted"
        assert config.top_k == 20
        assert config.enable_rerank is False

    def test_from_dict(self):
        data = {"bm25_k1": 1.2, "top_k": 15, "unknown_field": "ignore"}
        config = HybridSearchConfig.from_dict(data)
        assert config.bm25_k1 == 1.2
        assert config.top_k == 15
        assert not hasattr(config, "unknown_field")


class TestBM25Index:
    """Test BM25Index class."""

    @pytest.fixture
    def sample_docs(self):
        return {
            "doc1": "The quick brown fox jumps over the lazy dog",
            "doc2": "A quick brown dog runs in the park",
            "doc3": "Machine learning is a subset of artificial intelligence",
            "doc4": "Deep learning uses neural networks for machine learning",
        }

    def test_creation(self):
        index = BM25Index()
        assert index.k1 == 1.5
        assert index.b == 0.75
        assert index._built is False

    def test_add_document(self):
        index = BM25Index()
        index.add_document("doc1", "test document content")
        assert len(index.documents) == 1
        assert "doc1" in index.doc_tokens

    def test_add_documents(self, sample_docs):
        index = BM25Index()
        index.add_documents(sample_docs)
        assert len(index.documents) == 4

    def test_build(self, sample_docs):
        index = BM25Index()
        index.add_documents(sample_docs)
        index.build()
        assert index._built is True
        assert index.avg_doc_length > 0
        assert len(index.idf) > 0

    def test_search_basic(self, sample_docs):
        index = BM25Index()
        index.add_documents(sample_docs)
        results = index.search("quick brown fox", top_k=2)
        assert len(results) <= 2
        assert results[0][0] == "doc1"  # doc1 should rank highest

    def test_search_irrelevant(self, sample_docs):
        index = BM25Index()
        index.add_documents(sample_docs)
        results = index.search("quantum physics", top_k=10)
        # Should return some results even if not perfect match
        assert isinstance(results, list)

    def test_search_empty_query(self, sample_docs):
        index = BM25Index()
        index.add_documents(sample_docs)
        results = index.search("", top_k=10)
        assert results == []

    def test_search_empty_index(self):
        index = BM25Index()
        results = index.search("test", top_k=10)
        assert results == []

    def test_get_stats(self, sample_docs):
        index = BM25Index()
        index.add_documents(sample_docs)
        index.build()
        stats = index.get_stats()
        assert stats["num_documents"] == 4
        assert stats["num_terms"] > 0
        assert stats["avg_doc_length"] > 0
        assert stats["built"] is True

    def test_custom_tokenizer(self):
        def custom_tokenize(text):
            return text.split()

        index = BM25Index(tokenizer=custom_tokenize)
        index.add_document("doc1", "custom tokenizer test")
        assert index.doc_tokens["doc1"] == ["custom", "tokenizer", "test"]

    def test_chinese_text(self):
        index = BM25Index()
        index.add_document("doc1", "这是一个中文测试文档 包含机器学习内容")
        index.add_document("doc2", "机器学习 是 人工智能 的 一个 分支")
        index.build()
        # Chinese text with spaces should work
        results = index.search("机器学习", top_k=2)
        assert len(results) > 0


class TestHybridSearchEngine:
    """Test HybridSearchEngine class."""

    @pytest.fixture
    def sample_docs(self):
        return {
            "doc1": "The quick brown fox jumps over the lazy dog",
            "doc2": "A quick brown dog runs in the park",
            "doc3": "Machine learning is a subset of artificial intelligence",
            "doc4": "Deep learning uses neural networks for machine learning",
            "doc5": "Python is a popular programming language for data science",
        }

    def test_creation(self):
        engine = HybridSearchEngine()
        assert engine.config.top_k == 10
        assert engine.semantic_search_fn is None

    def test_add_document(self):
        engine = HybridSearchEngine()
        engine.add_document("doc1", "test content", metadata={"source": "web"})
        assert len(engine.documents) == 1
        assert engine.doc_metadata["doc1"]["source"] == "web"

    def test_add_documents(self, sample_docs):
        engine = HybridSearchEngine()
        engine.add_documents(sample_docs)
        assert len(engine.documents) == 5

    def test_build(self, sample_docs):
        engine = HybridSearchEngine()
        engine.add_documents(sample_docs)
        engine.build()
        assert engine.bm25._built is True

    def test_search_basic(self, sample_docs):
        engine = HybridSearchEngine()
        engine.add_documents(sample_docs)
        results = engine.search("quick brown fox", top_k=3)
        assert len(results) > 0
        assert results[0].doc_id == "doc1"
        assert results[0].final_score > 0

    def test_search_machine_learning(self, sample_docs):
        engine = HybridSearchEngine()
        engine.add_documents(sample_docs)
        results = engine.search("machine learning neural networks", top_k=3)
        assert len(results) > 0
        # doc3 or doc4 should rank high
        top_ids = [r.doc_id for r in results[:2]]
        assert "doc3" in top_ids or "doc4" in top_ids

    def test_search_with_semantic_callback(self, sample_docs):
        # Mock semantic search function
        def mock_semantic(query, top_k):
            return [
                ("doc3", 0.95, sample_docs["doc3"]),
                ("doc4", 0.90, sample_docs["doc4"]),
            ]

        config = HybridSearchConfig(fusion_method="rrf", top_k=3)
        engine = HybridSearchEngine(config=config, semantic_search_fn=mock_semantic)
        engine.add_documents(sample_docs)
        results = engine.search("machine learning", top_k=3)
        assert len(results) > 0
        # Semantic results should influence ranking
        all_ids = [r.doc_id for r in results]
        assert "doc3" in all_ids or "doc4" in all_ids

    def test_weighted_fusion(self, sample_docs):
        config = HybridSearchConfig(
            fusion_method="weighted",
            bm25_weight=0.7,
            semantic_weight=0.3,
            enable_rerank=False,
        )
        engine = HybridSearchEngine(config=config)
        engine.add_documents(sample_docs)
        results = engine.search("quick brown", top_k=3)
        assert len(results) > 0
        assert results[0].fused_score > 0

    def test_rerank_disabled(self, sample_docs):
        config = HybridSearchConfig(enable_rerank=False)
        engine = HybridSearchEngine(config=config)
        engine.add_documents(sample_docs)
        results = engine.search("machine learning", top_k=3)
        assert len(results) > 0
        # Without rerank, rerank_score should be 0
        for r in results:
            assert r.rerank_score == 0.0

    def test_deduplication(self):
        docs = {
            "doc1": "The quick brown fox jumps over the lazy dog",
            "doc2": "The quick brown fox jumps over the lazy dog",  # Duplicate
            "doc3": "Completely different content here",
        }
        config = HybridSearchConfig(deduplicate=True, enable_rerank=False)
        engine = HybridSearchEngine(config=config)
        engine.add_documents(docs)
        results = engine.search("quick brown fox", top_k=10)
        # Should deduplicate doc1 and doc2
        assert len(results) < 3

    def test_min_score_filter(self, sample_docs):
        config = HybridSearchConfig(min_score=100.0, enable_rerank=False)  # Very high threshold
        engine = HybridSearchEngine(config=config)
        engine.add_documents(sample_docs)
        results = engine.search("test", top_k=10)
        # Should filter out all results
        assert len(results) == 0

    def test_get_stats(self, sample_docs):
        engine = HybridSearchEngine()
        engine.add_documents(sample_docs)
        engine.build()
        stats = engine.get_stats()
        assert stats["num_documents"] == 5
        assert "bm25_stats" in stats
        assert "config" in stats
        assert stats["semantic_search_enabled"] is False

    def test_empty_query(self, sample_docs):
        engine = HybridSearchEngine()
        engine.add_documents(sample_docs)
        results = engine.search("", top_k=10)
        assert isinstance(results, list)


class TestConvenienceFunction:
    """Test create_hybrid_search convenience function."""

    def test_create_hybrid_search(self):
        docs = {
            "doc1": "The quick brown fox",
            "doc2": "Machine learning basics",
        }
        engine = create_hybrid_search(docs, top_k=5)
        assert isinstance(engine, HybridSearchEngine)
        assert len(engine.documents) == 2
        assert engine.config.top_k == 5
        assert engine.bm25._built is True

    def test_create_with_semantic_fn(self):
        docs = {"doc1": "test"}
        def mock_fn(query, k):
            return []
        engine = create_hybrid_search(docs, semantic_search_fn=mock_fn)
        assert engine.semantic_search_fn is not None
