"""Tests for RAG optimizer module."""

from webscout_mcp.rag_optimizer import (
    Chunk,
    ContextCompressor,
    QueryRewriter,
    RAGOptimizer,
    RAGResponse,
    SemanticChunker,
    optimize_rag,
)

# Sample document for testing
SAMPLE_DOCUMENT = """
Python is a popular programming language known for its simplicity and readability.

It was created by Guido van Rossum and first released in 1991. Python emphasizes code readability and allows programmers to express concepts in fewer lines of code.

Python is widely used in web development, data science, artificial intelligence, scientific computing, and many other fields.

The language features dynamic typing, automatic memory management, and a large standard library. Python supports multiple programming paradigms, including procedural, object-oriented, and functional programming.

One of Python's key strengths is its ecosystem of libraries and frameworks. Popular libraries include NumPy for numerical computing, Pandas for data manipulation, TensorFlow for machine learning, and Django for web development.

Python has a vibrant community and extensive documentation. The Python Package Index (PyPI) hosts hundreds of thousands of third-party packages that extend Python's capabilities.
"""


class TestChunk:
    """Test Chunk class."""

    def test_creation(self):
        chunk = Chunk(text="Test content", chunk_id="chunk_0")
        assert chunk.text == "Test content"
        assert chunk.chunk_id == "chunk_0"
        assert chunk.score == 0.0

    def test_to_dict(self):
        chunk = Chunk(text="Test", word_count=5, score=0.8)
        data = chunk.to_dict()
        assert data["text"] == "Test"
        assert data["word_count"] == 5
        assert data["score"] == 0.8


class TestRAGResponse:
    """Test RAGResponse class."""

    def test_creation(self):
        resp = RAGResponse(query="test")
        assert resp.query == "test"
        assert resp.confidence == 0.0

    def test_to_dict(self):
        resp = RAGResponse(query="test", answer="Test answer", confidence=0.9)
        data = resp.to_dict()
        assert data["query"] == "test"
        assert data["answer"] == "Test answer"
        assert data["confidence"] == 0.9


class TestSemanticChunker:
    """Test SemanticChunker class."""

    def test_creation(self):
        chunker = SemanticChunker(max_chunk_size=200)
        assert chunker.max_chunk_size == 200

    def test_chunk_document(self):
        chunker = SemanticChunker(max_chunk_size=100)
        chunks = chunker.chunk(SAMPLE_DOCUMENT)
        assert len(chunks) > 1
        assert all(c.text for c in chunks)
        assert all(c.word_count > 0 for c in chunks)

    def test_chunk_empty(self):
        chunker = SemanticChunker()
        chunks = chunker.chunk("")
        assert len(chunks) == 0

    def test_chunk_short(self):
        chunker = SemanticChunker()
        chunks = chunker.chunk("Short text")
        assert len(chunks) == 1
        assert chunks[0].text == "Short text"

    def test_chunk_with_metadata(self):
        chunker = SemanticChunker()
        metadata = {"source": "test", "url": "https://example.com"}
        chunks = chunker.chunk(SAMPLE_DOCUMENT, metadata=metadata)
        assert all(c.metadata.get("source") == "test" for c in chunks)

    def test_split_paragraphs(self):
        chunker = SemanticChunker()
        text = "Para 1.\n\nPara 2.\n\nPara 3."
        paragraphs = chunker._split_paragraphs(text)
        assert len(paragraphs) == 3
        assert all(p[0] for p in paragraphs)


class TestContextCompressor:
    """Test ContextCompressor class."""

    def test_creation(self):
        compressor = ContextCompressor(max_tokens=1000)
        assert compressor.max_tokens == 1000

    def test_compress_chunks(self):
        compressor = ContextCompressor(max_tokens=500)
        chunks = [
            Chunk(text="Python is great for data science.", word_count=6, token_count=8),
            Chunk(text="JavaScript is used for web development.", word_count=7, token_count=9),
            Chunk(text="Machine learning is a subset of AI.", word_count=8, token_count=10),
        ]
        compressed, used = compressor.compress(chunks, query="python data science")
        assert len(compressed) > 0
        assert len(used) > 0
        assert "Python" in compressed or "python" in compressed.lower()

    def test_compress_empty(self):
        compressor = ContextCompressor()
        compressed, used = compressor.compress([], query="test")
        assert compressed == ""
        assert len(used) == 0

    def test_score_chunks(self):
        compressor = ContextCompressor()
        chunks = [
            Chunk(text="Python programming language"),
            Chunk(text="Cooking recipes"),
        ]
        scored = compressor._score_chunks(chunks, "python")
        assert scored[0].score > scored[1].score

    def test_extract_key_sentences(self):
        compressor = ContextCompressor()
        text = "Python is great. It is used for data science. JavaScript is for web. Cooking is fun."
        sentences = compressor._extract_key_sentences(text, "python data science")
        assert len(sentences) > 0
        assert any("Python" in s or "python" in s.lower() for s in sentences)


class TestQueryRewriter:
    """Test QueryRewriter class."""

    def test_creation(self):
        rewriter = QueryRewriter()
        assert rewriter is not None

    def test_rewrite_query(self):
        rewriter = QueryRewriter()
        rewritten, changed = rewriter.rewrite("what is python")
        assert "python" in rewritten.lower()
        assert isinstance(changed, bool)

    def test_rewrite_empty(self):
        rewriter = QueryRewriter()
        rewritten, changed = rewriter.rewrite("")
        assert rewritten == ""
        assert changed is False

    def test_expand_query(self):
        rewriter = QueryRewriter()
        variations = rewriter.expand("how to learn python")
        assert len(variations) >= 1
        assert "how to learn python" in variations


class TestRAGOptimizer:
    """Test RAGOptimizer class."""

    def test_creation(self):
        optimizer = RAGOptimizer(max_chunk_size=200)
        assert optimizer.chunker.max_chunk_size == 200

    def test_prepare_documents(self):
        optimizer = RAGOptimizer(max_chunk_size=100)
        chunks = optimizer.prepare_documents([SAMPLE_DOCUMENT])
        assert len(chunks) > 1
        assert all(c.metadata.get("document_index") == 0 for c in chunks)

    def test_retrieve(self):
        optimizer = RAGOptimizer(max_chunk_size=100)
        chunks = optimizer.prepare_documents([SAMPLE_DOCUMENT])
        response = optimizer.retrieve("python programming", chunks, top_k=3)
        assert response.query == "python programming"
        assert len(response.chunks) > 0
        assert response.retrieval_score >= 0
        assert response.processing_time_ms > 0

    def test_retrieve_no_match(self):
        optimizer = RAGOptimizer()
        chunks = [Chunk(text="Cooking recipes")]
        response = optimizer.retrieve("quantum physics", chunks)
        assert len(response.chunks) > 0  # Still returns chunks, just low score
        assert response.confidence < 0.5

    def test_get_stats(self):
        optimizer = RAGOptimizer(max_chunk_size=300, max_context_tokens=1500)
        stats = optimizer.get_stats()
        assert stats["max_chunk_size"] == 300
        assert stats["max_context_tokens"] == 1500


class TestConvenienceFunction:
    """Test optimize_rag convenience function."""

    def test_optimize_rag(self):
        response = optimize_rag(
            "python programming",
            [SAMPLE_DOCUMENT],
            top_k=2,
            max_chunk_size=100,
        )
        assert isinstance(response, RAGResponse)
        assert response.query == "python programming"
        assert len(response.chunks) > 0
