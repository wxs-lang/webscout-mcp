"""Vector search and RAG examples.

Demonstrates how to use the vector store for:
- Semantic search
- Document indexing
- RAG (Retrieval-Augmented Generation) question answering
- Document management
"""
from webscout_mcp.vector_store import VectorStore, RAGEngine, Document, VectorStoreConfig


def example_semantic_search():
    """Example: Semantic search over documents."""
    print("=" * 60)
    print("Example: Semantic Search")
    print("=" * 60)

    # Initialize vector store with local embedding model
    config = VectorStoreConfig(
        embedding_backend="local",
        embedding_model="BAAI/bge-small-zh-v1.5",
        persist_dir="/tmp/webscout_vector_demo",
    )
    store = VectorStore(config=config)

    # Check if vector store is available
    if not store.is_available():
        print("ChromaDB not available. Install with:")
        print("  pip install chromadb sentence-transformers")
        return

    # Clear existing data for demo
    store.clear()

    # Add sample documents
    documents = [
        Document.from_text(
            "Python is a high-level programming language known for its simplicity and readability. "
            "It is widely used in web development, data science, machine learning, and automation.",
            source="https://example.com/python",
            metadata={"category": "programming", "language": "Python"},
        ),
        Document.from_text(
            "JavaScript is a programming language that enables interactive web pages. "
            "It is an essential part of web applications alongside HTML and CSS. "
            "Node.js allows JavaScript to run on servers.",
            source="https://example.com/javascript",
            metadata={"category": "programming", "language": "JavaScript"},
        ),
        Document.from_text(
            "Machine learning is a subset of artificial intelligence that enables systems "
            "to learn and improve from experience without being explicitly programmed. "
            "Common algorithms include neural networks, decision trees, and support vector machines.",
            source="https://example.com/ml",
            metadata={"category": "ai", "topic": "machine-learning"},
        ),
        Document.from_text(
            "Web scraping is the process of extracting data from websites. "
            "It involves fetching web pages and parsing the HTML to extract structured data. "
            "Tools like BeautifulSoup, Scrapy, and Playwright are commonly used.",
            source="https://example.com/scraping",
            metadata={"category": "web", "topic": "scraping"},
        ),
    ]

    print("Adding documents to vector store...")
    for doc in documents:
        chunks = store.add_document(doc)
        print(f"  Added: {doc.source} ({chunks} chunks)")

    # Perform semantic searches
    queries = [
        "What programming language is good for data science?",
        "How do I extract data from websites?",
        "What is AI and machine learning?",
        "Which language runs in web browsers?",
    ]

    print("\nSemantic Search Results:")
    print("-" * 60)
    for query in queries:
        results = store.search(query, n_results=2)
        print(f"\nQuery: {query}")
        for result in results:
            print(f"  [{result.score:.3f}] {result.document.source}")
            print(f"       {result.document.content[:80]}...")


def example_rag():
    """Example: RAG (Retrieval-Augmented Generation) question answering."""
    print("\n" + "=" * 60)
    print("Example: RAG Question Answering")
    print("=" * 60)

    # Initialize vector store
    config = VectorStoreConfig(
        embedding_backend="local",
        embedding_model="BAAI/bge-small-zh-v1.5",
        persist_dir="/tmp/webscout_vector_demo",
    )
    store = VectorStore(config=config)

    if not store.is_available():
        print("ChromaDB not available. Skipping example.")
        return

    # Initialize RAG engine (uses AI processor for answer generation)
    rag = RAGEngine(vector_store=store)

    # Ask questions
    questions = [
        "What is Python used for?",
        "How does web scraping work?",
    ]

    print("\nRAG Question Answering:")
    print("-" * 60)
    for question in questions:
        print(f"\nQuestion: {question}")

        # Retrieve relevant documents
        docs = rag.retrieve(question, n_results=2)
        print(f"  Retrieved {len(docs)} relevant documents")
        for doc in docs:
            print(f"    - {doc.document.source} (score: {doc.score:.3f})")

        # Generate answer (requires AI backend)
        try:
            result = rag.query(question, n_results=2)
            print(f"  Answer: {result['answer'][:200]}...")
            if result.get("sources"):
                print(f"  Sources: {', '.join(result['sources'])}")
        except Exception as exc:
            print(f"  Answer generation requires AI backend: {exc}")
            print("  Install Ollama or set OpenAI API key to enable answer generation.")


def example_document_management():
    """Example: Document management operations."""
    print("\n" + "=" * 60)
    print("Example: Document Management")
    print("=" * 60)

    config = VectorStoreConfig(
        embedding_backend="local",
        embedding_model="BAAI/bge-small-zh-v1.5",
        persist_dir="/tmp/webscout_vector_demo",
    )
    store = VectorStore(config=config)

    if not store.is_available():
        print("ChromaDB not available. Skipping example.")
        return

    # Get statistics
    stats = store.get_stats()
    print(f"\nVector Store Statistics:")
    print(f"  Total chunks: {stats['total_chunks']}")
    print(f"  Vector DB: {stats['vector_db']}")
    print(f"  Embedding backend: {stats['embedding_backend']}")
    print(f"  Embedding model: {stats['embedding_model']}")

    # Count documents
    count = store.count()
    print(f"  Document count: {count}")

    # Clear all documents
    print("\nClearing all documents...")
    store.clear()
    print(f"  New count: {store.count()}")


def run_all_examples():
    """Run all vector search examples."""
    print("\n" + "=" * 60)
    print("  Vector Search & RAG Examples")
    print("=" * 60 + "\n")

    example_semantic_search()
    example_rag()
    example_document_management()

    print("\n" + "=" * 60)
    print("All examples completed!")
    print("=" * 60)


if __name__ == "__main__":
    run_all_examples()
