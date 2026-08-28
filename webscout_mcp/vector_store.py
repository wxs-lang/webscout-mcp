"""Vector store and RAG (Retrieval-Augmented Generation) module for webscout-mcp.
Provides semantic search and RAG capabilities using local vector database and embedding models.

Features:
- Local vector database (Chroma)
- Semantic search (not just keyword matching)
- RAG (Retrieval-Augmented Generation) for question answering
- Support for local embedding models (sentence-transformers)
- Support for API-based embedding models (OpenAI, etc.)
- Document chunking and indexing
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any, Optional

from .logging import get_logger

log = get_logger(__name__)


@dataclass
class VectorStoreConfig:
    """Configuration for vector store."""

    # Vector database: chroma
    vector_db: str = "chroma"
    # Persistence directory
    persist_dir: str = "~/.cache/webscout/vector_db"
    # Embedding backend: local (sentence-transformers), openai, custom
    embedding_backend: str = "local"
    # Embedding model name
    embedding_model: str = "BAAI/bge-small-zh-v1.5"
    # API base URL (for custom backend)
    api_base: str = ""
    # API key (for OpenAI/custom)
    api_key: str = ""
    # Chunk size for document splitting
    chunk_size: int = 500
    # Chunk overlap
    chunk_overlap: int = 50
    # Maximum number of results to retrieve
    max_results: int = 5
    # Similarity threshold (0-1)
    similarity_threshold: float = 0.5

    @classmethod
    def from_env(cls) -> "VectorStoreConfig":
        """Load configuration from environment variables."""
        import os

        return cls(
            vector_db=os.environ.get("WEBSCOUT_VECTOR_DB", "chroma"),
            persist_dir=os.environ.get("WEBSCOUT_VECTOR_PERSIST_DIR", "~/.cache/webscout/vector_db"),
            embedding_backend=os.environ.get("WEBSCOUT_EMBEDDING_BACKEND", "local"),
            embedding_model=os.environ.get("WEBSCOUT_EMBEDDING_MODEL", "BAAI/bge-small-zh-v1.5"),
            api_base=os.environ.get("WEBSCOUT_EMBEDDING_API_BASE", ""),
            api_key=os.environ.get("WEBSCOUT_EMBEDDING_API_KEY", ""),
            chunk_size=int(os.environ.get("WEBSCOUT_CHUNK_SIZE", "500")),
            chunk_overlap=int(os.environ.get("WEBSCOUT_CHUNK_OVERLAP", "50")),
            max_results=int(os.environ.get("WEBSCOUT_MAX_RESULTS", "5")),
            similarity_threshold=float(os.environ.get("WEBSCOUT_SIMILARITY_THRESHOLD", "0.5")),
        )


@dataclass
class Document:
    """A document to be indexed in the vector store."""

    id: str
    content: str
    metadata: dict = field(default_factory=dict)
    source: str = ""

    @classmethod
    def from_text(cls, text: str, source: str = "", metadata: Optional[dict] = None) -> "Document":
        """Create a document from text."""
        doc_id = hashlib.md5(f"{source}:{text[:100]}".encode()).hexdigest()
        return cls(
            id=doc_id,
            content=text,
            metadata=metadata or {},
            source=source,
        )


@dataclass
class SearchResult:
    """A search result from the vector store."""

    document: Document
    score: float
    rank: int

    def to_dict(self) -> dict:
        return {
            "document": {
                "id": self.document.id,
                "content": self.document.content,
                "metadata": self.document.metadata,
                "source": self.document.source,
            },
            "score": self.score,
            "rank": self.rank,
        }


class VectorStore:
    """Vector store for semantic search and RAG.

    Uses Chroma as the vector database and supports multiple embedding backends.
    """

    def __init__(self, config: Optional[VectorStoreConfig] = None) -> None:
        self.config = config or VectorStoreConfig.from_env()
        self._client = None
        self._collection = None
        self._embedding_function = None

    def is_available(self) -> bool:
        """Check if vector store is available."""
        try:
            import chromadb

            return True
        except ImportError:
            return False

    def _get_client(self):
        """Get or create Chroma client."""
        if self._client:
            return self._client

        try:
            import os

            import chromadb
            from chromadb.config import Settings

            persist_dir = os.path.expanduser(self.config.persist_dir)
            os.makedirs(persist_dir, exist_ok=True)
            self._client = chromadb.PersistentClient(
                path=persist_dir,
                settings=Settings(anonymized_telemetry=False),
            )
        except ImportError:
            raise ImportError("chromadb is required for vector store. Install with: pip install chromadb")

        return self._client

    def _get_embedding_function(self):
        """Get or create embedding function."""
        if self._embedding_function:
            return self._embedding_function

        if self.config.embedding_backend == "local":
            self._embedding_function = self._create_local_embedding_function()
        elif self.config.embedding_backend in ("openai", "custom"):
            self._embedding_function = self._create_api_embedding_function()
        else:
            raise ValueError(f"Unsupported embedding backend: {self.config.embedding_backend}")

        return self._embedding_function

    def _create_local_embedding_function(self):
        """Create local embedding function using sentence-transformers."""
        try:
            from chromadb.utils import embedding_functions

            return embedding_functions.SentenceTransformerEmbeddingFunction(
                model_name=self.config.embedding_model,
            )
        except ImportError:
            raise ImportError(
                "sentence-transformers is required for local embedding. "
                "Install with: pip install sentence-transformers"
            )

    def _create_api_embedding_function(self):
        """Create API-based embedding function."""
        try:
            from chromadb.utils import embedding_functions

            return embedding_functions.OpenAIEmbeddingFunction(
                api_key=self.config.api_key,
                model_name=self.config.embedding_model,
                api_base=self.config.api_base or None,
            )
        except ImportError:
            raise ImportError("openai is required for API embedding. Install with: pip install openai")

    def _get_collection(self):
        """Get or create collection."""
        if self._collection:
            return self._collection

        client = self._get_client()
        embedding_function = self._get_embedding_function()
        self._collection = client.get_or_create_collection(
            name="webscout_documents",
            embedding_function=embedding_function,
            metadata={"hnsw:space": "cosine"},
        )
        return self._collection

    def _chunk_text(self, text: str) -> list[str]:
        """Split text into chunks."""
        chunks = []
        start = 0
        while start < len(text):
            end = start + self.config.chunk_size
            chunk = text[start:end]
            if chunk.strip():
                chunks.append(chunk)
            start = end - self.config.chunk_overlap
        return chunks

    def add_document(self, document: Document) -> int:
        """Add a document to the vector store.

        Args:
            document: Document to add.

        Returns:
            Number of chunks added.
        """
        collection = self._get_collection()
        chunks = self._chunk_text(document.content)

        for i, chunk in enumerate(chunks):
            chunk_id = f"{document.id}_chunk_{i}"
            metadata = {
                **document.metadata,
                "source": document.source,
                "chunk_index": i,
                "total_chunks": len(chunks),
                "document_id": document.id,
            }
            collection.upsert(
                ids=[chunk_id],
                documents=[chunk],
                metadatas=[metadata],
            )

        log.info(
            "Document added to vector store",
            extra={
                "document_id": document.id,
                "chunks": len(chunks),
                "source": document.source,
            },
        )
        return len(chunks)

    def add_texts(
        self,
        texts: list[str],
        source: str = "",
        metadata: Optional[dict] = None,
    ) -> int:
        """Add multiple texts to the vector store.

        Args:
            texts: List of texts to add.
            source: Source identifier.
            metadata: Additional metadata.

        Returns:
            Total number of chunks added.
        """
        total_chunks = 0
        for text in texts:
            doc = Document.from_text(text, source=source, metadata=metadata)
            total_chunks += self.add_document(doc)
        return total_chunks

    def search(self, query: str, n_results: Optional[int] = None) -> list[SearchResult]:
        """Search for documents similar to query.

        Args:
            query: Search query.
            n_results: Number of results to return.

        Returns:
            List of search results.
        """
        collection = self._get_collection()
        n = n_results or self.config.max_results

        results = collection.query(
            query_texts=[query],
            n_results=n,
        )

        search_results = []
        if results and results["documents"] and results["documents"][0]:
            for i, (doc_text, doc_metadata, distance) in enumerate(
                zip(
                    results["documents"][0],
                    results["metadatas"][0],
                    results["distances"][0],
                )
            ):
                # Convert distance to similarity score (cosine distance -> similarity)
                similarity = 1.0 - distance
                if similarity >= self.config.similarity_threshold:
                    doc = Document(
                        id=doc_metadata.get("document_id", results["ids"][0][i]),
                        content=doc_text,
                        metadata=doc_metadata,
                        source=doc_metadata.get("source", ""),
                    )
                    search_results.append(
                        SearchResult(
                            document=doc,
                            score=similarity,
                            rank=i + 1,
                        )
                    )

        return search_results

    def delete_document(self, document_id: str) -> int:
        """Delete a document from the vector store.

        Args:
            document_id: ID of document to delete.

        Returns:
            Number of chunks deleted.
        """
        collection = self._get_collection()
        results = collection.get(
            where={"document_id": document_id},
        )
        if results and results["ids"]:
            collection.delete(ids=results["ids"])
            log.info(
                "Document deleted from vector store",
                extra={
                    "document_id": document_id,
                    "chunks": len(results["ids"]),
                },
            )
            return len(results["ids"])
        return 0

    def clear(self) -> None:
        """Clear all documents from the vector store."""
        client = self._get_client()
        try:
            client.delete_collection("webscout_documents")
            self._collection = None
            log.info("Vector store cleared")
        except Exception as exc:
            log.warning("Failed to clear vector store", extra={"error": str(exc)})

    def count(self) -> int:
        """Get total number of chunks in the vector store."""
        collection = self._get_collection()
        return collection.count()

    def get_stats(self) -> dict:
        """Get vector store statistics."""
        return {
            "total_chunks": self.count(),
            "vector_db": self.config.vector_db,
            "embedding_backend": self.config.embedding_backend,
            "embedding_model": self.config.embedding_model,
            "persist_dir": self.config.persist_dir,
        }


class RAGEngine:
    """RAG (Retrieval-Augmented Generation) engine.

    Combines vector search with AI generation for question answering.
    """

    def __init__(
        self,
        vector_store: Optional[VectorStore] = None,
        ai_processor=None,
    ) -> None:
        self.vector_store = vector_store or VectorStore()
        self.ai_processor = ai_processor

    def is_available(self) -> bool:
        """Check if RAG engine is available."""
        return self.vector_store.is_available()

    def add_document(self, document: Document) -> int:
        """Add a document to the RAG engine."""
        return self.vector_store.add_document(document)

    def add_texts(self, texts: list[str], source: str = "") -> int:
        """Add multiple texts to the RAG engine."""
        return self.vector_store.add_texts(texts, source=source)

    def retrieve(self, query: str, n_results: int = 5) -> list[SearchResult]:
        """Retrieve relevant documents for a query."""
        return self.vector_store.search(query, n_results=n_results)

    def generate_answer(self, query: str, context: str) -> Any:
        """Generate answer using AI processor."""
        if not self.ai_processor:
            from .ai_processor import AIProcessor

            self.ai_processor = AIProcessor()
        return self.ai_processor.answer_question(context, query)

    def query(self, question: str, n_results: int = 5) -> dict:
        """Answer a question using RAG.

        Args:
            question: Question to answer.
            n_results: Number of documents to retrieve.

        Returns:
            Dictionary with answer, sources, and retrieved documents.
        """
        # Retrieve relevant documents
        results = self.retrieve(question, n_results=n_results)

        if not results:
            return {
                "answer": "未找到相关文档，无法回答该问题。",
                "sources": [],
                "documents": [],
            }

        # Build context from retrieved documents
        context_parts = []
        sources = []
        for result in results:
            context_parts.append(f"[文档{result.rank}]\n{result.document.content}")
            if result.document.source and result.document.source not in sources:
                sources.append(result.document.source)

        context = "\n\n".join(context_parts)

        # Generate answer
        ai_response = self.generate_answer(question, context)

        return {
            "answer": ai_response.content if hasattr(ai_response, "content") else str(ai_response),
            "sources": sources,
            "documents": [r.to_dict() for r in results],
            "error": ai_response.error if hasattr(ai_response, "error") else None,
        }

    def clear(self) -> None:
        """Clear all documents from the RAG engine."""
        self.vector_store.clear()

    def get_stats(self) -> dict:
        """Get RAG engine statistics."""
        return self.vector_store.get_stats()


def is_vector_store_available() -> bool:
    """Check if vector store is available."""
    try:
        import chromadb

        return True
    except ImportError:
        return False
