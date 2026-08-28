"""Tests for vector store and RAG module."""
import pytest
from webscout_mcp.vector_store import (
    VectorStoreConfig,
    Document,
    SearchResult,
    VectorStore,
    RAGEngine,
    is_vector_store_available,
)


class TestVectorStoreConfig:
    """Test vector store configuration."""

    def test_default_config(self):
        config = VectorStoreConfig()
        assert config.vector_db == "chroma"
        assert config.embedding_backend == "local"
        assert config.embedding_model == "BAAI/bge-small-zh-v1.5"
        assert config.chunk_size == 500
        assert config.chunk_overlap == 50
        assert config.max_results == 5
        assert config.similarity_threshold == 0.5

    def test_custom_config(self):
        config = VectorStoreConfig(
            vector_db="chroma",
            embedding_backend="openai",
            embedding_model="text-embedding-3-small",
            api_key="test-key",
            chunk_size=1000,
            chunk_overlap=100,
            max_results=10,
        )
        assert config.embedding_backend == "openai"
        assert config.embedding_model == "text-embedding-3-small"
        assert config.api_key == "test-key"
        assert config.chunk_size == 1000
        assert config.chunk_overlap == 100
        assert config.max_results == 10

    def test_from_env(self, monkeypatch):
        monkeypatch.setenv("WEBSCOUT_VECTOR_DB", "chroma")
        monkeypatch.setenv("WEBSCOUT_EMBEDDING_BACKEND", "openai")
        monkeypatch.setenv("WEBSCOUT_EMBEDDING_MODEL", "text-embedding-3-small")
        monkeypatch.setenv("WEBSCOUT_EMBEDDING_API_KEY", "env-key")
        monkeypatch.setenv("WEBSCOUT_CHUNK_SIZE", "800")
        monkeypatch.setenv("WEBSCOUT_MAX_RESULTS", "8")

        config = VectorStoreConfig.from_env()
        assert config.vector_db == "chroma"
        assert config.embedding_backend == "openai"
        assert config.embedding_model == "text-embedding-3-small"
        assert config.api_key == "env-key"
        assert config.chunk_size == 800
        assert config.max_results == 8


class TestDocument:
    """Test Document class."""

    def test_document_creation(self):
        doc = Document(
            id="test-id",
            content="Test content",
            metadata={"key": "value"},
            source="test-source",
        )
        assert doc.id == "test-id"
        assert doc.content == "Test content"
        assert doc.metadata == {"key": "value"}
        assert doc.source == "test-source"

    def test_from_text(self):
        doc = Document.from_text(
            "Test content for document",
            source="https://example.com",
            metadata={"author": "test"},
        )
        assert doc.id is not None
        assert doc.content == "Test content for document"
        assert doc.source == "https://example.com"
        assert doc.metadata == {"author": "test"}

    def test_from_text_generates_unique_ids(self):
        doc1 = Document.from_text("Content 1", source="source1")
        doc2 = Document.from_text("Content 2", source="source2")
        assert doc1.id != doc2.id


class TestSearchResult:
    """Test SearchResult class."""

    def test_search_result_creation(self):
        doc = Document(id="test", content="test")
        result = SearchResult(document=doc, score=0.95, rank=1)
        assert result.document == doc
        assert result.score == 0.95
        assert result.rank == 1

    def test_search_result_to_dict(self):
        doc = Document(id="test", content="test", source="source")
        result = SearchResult(document=doc, score=0.95, rank=1)
        data = result.to_dict()
        assert data["document"]["id"] == "test"
        assert data["document"]["content"] == "test"
        assert data["document"]["source"] == "source"
        assert data["score"] == 0.95
        assert data["rank"] == 1


class TestVectorStore:
    """Test VectorStore class."""

    def test_vector_store_creation(self):
        config = VectorStoreConfig()
        store = VectorStore(config=config)
        assert store.config == config

    def test_is_available(self):
        # Just verify it doesn't raise
        result = is_vector_store_available()
        assert isinstance(result, bool)

    def test_unsupported_embedding_backend(self):
        config = VectorStoreConfig(embedding_backend="unsupported")
        store = VectorStore(config=config)
        with pytest.raises(ValueError, match="Unsupported embedding backend"):
            store._get_embedding_function()

    def test_chunk_text(self):
        config = VectorStoreConfig(chunk_size=100, chunk_overlap=20)
        store = VectorStore(config=config)
        text = "a" * 250
        chunks = store._chunk_text(text)
        assert len(chunks) > 1
        # First chunk should be chunk_size
        assert len(chunks[0]) == 100

    def test_chunk_text_empty(self):
        config = VectorStoreConfig()
        store = VectorStore(config=config)
        chunks = store._chunk_text("")
        assert chunks == []

    def test_chunk_text_short(self):
        config = VectorStoreConfig(chunk_size=500)
        store = VectorStore(config=config)
        text = "Short text"
        chunks = store._chunk_text(text)
        assert len(chunks) == 1
        assert chunks[0] == "Short text"


class TestRAGEngine:
    """Test RAGEngine class."""

    def test_rag_engine_creation(self):
        engine = RAGEngine()
        assert engine.vector_store is not None

    def test_rag_engine_with_custom_store(self):
        config = VectorStoreConfig()
        store = VectorStore(config=config)
        engine = RAGEngine(vector_store=store)
        assert engine.vector_store == store

    def test_is_available(self):
        engine = RAGEngine()
        result = engine.is_available()
        assert isinstance(result, bool)


class TestUtilityFunctions:
    """Test utility functions."""

    def test_is_vector_store_available(self):
        result = is_vector_store_available()
        assert isinstance(result, bool)
