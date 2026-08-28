# Tutorial 1: Getting Started with webscout-mcp

## Overview

In this tutorial, you'll learn the basics of webscout-mcp:
- Installation and setup
- Basic web search
- Fetching web content
- AI-powered content processing
- Running the MCP server

## Prerequisites

- Python 3.10+
- pip
- Internet connection

## Step 1: Installation

```bash
# Create a virtual environment (recommended)
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install webscout-mcp
pip install webscout-mcp

# Verify installation
python -c "import webscout_mcp; print(f'webscout-mcp version: {webscout_mcp.__version__}')"
```

## Step 2: Basic Web Search

Create a file `search_example.py`:

```python
from webscout_mcp import WebScout

# Create a client
scout = WebScout()

# Search the web
results = scout.search("Python programming tutorial", max_results=5)

print(f"Found {len(results)} results:\n")
for i, result in enumerate(results, 1):
    print(f"{i}. {result.title}")
    print(f"   URL: {result.url}")
    print(f"   Snippet: {result.snippet[:100]}...")
    print()
```

Run it:
```bash
python search_example.py
```

### Search Options

```python
# Search with specific backend
results = scout.search("query", backends=["bing"])

# Search with language and region
results = scout.search("query", language="zh-CN", region="CN")

# Search with time range
results = scout.search("query", time_range="week")  # day, week, month, year
```

## Step 3: Fetching Web Content

Create a file `fetch_example.py`:

```python
from webscout_mcp import WebScout

scout = WebScout()

# Fetch a web page
page = scout.fetch("https://example.com")

print(f"URL: {page.url}")
print(f"Title: {page.title}")
print(f"Status: {page.status_code}")
print(f"Content length: {len(page.text)} characters")
print(f"\nContent preview:\n{page.text[:300]}...")
```

### Advanced Fetching

```python
# Fetch with custom headers
page = scout.fetch(
    "https://example.com",
    headers={"User-Agent": "Mozilla/5.0 ..."},
    timeout=30,
    follow_redirects=True,
)

# Batch fetch multiple URLs
urls = ["https://example.com/page1", "https://example.com/page2"]
pages = scout.fetch_batch(urls, max_concurrent=5)
```

## Step 4: AI Content Processing

Create a file `ai_example.py`:

```python
from webscout_mcp import WebScout

scout = WebScout()

# Sample text
text = """
Python is a high-level, general-purpose programming language. Its design
philosophy emphasizes code readability with the use of significant indentation.

Python is dynamically typed and garbage-collected. It supports multiple
programming paradigms, including structured, object-oriented, and functional
programming.

Python was created by Guido van Rossum and first released in 1991.
"""

# Summarize text
summary = scout.summarize(text, max_length=100)
print(f"Summary:\n{summary}\n")

# Classify text
category = scout.classify(text, categories=["programming", "science", "history"])
print(f"Category: {category}")

# Analyze sentiment
sentiment = scout.analyze_sentiment(text)
print(f"Sentiment: {sentiment.label} (confidence: {sentiment.confidence:.2f})")

# Extract keywords
keywords = scout.extract_keywords(text, top_k=5)
print(f"\nKeywords:")
for keyword, score in keywords:
    print(f"  - {keyword}: {score:.4f}")
```

## Step 5: Running the MCP Server

### Stdio Transport (for local AI clients)

```bash
# Start MCP server with stdio transport
webscout-mcp

# Or with Python
python -m webscout_mcp
```

### SSE Transport (for remote access)

```bash
# Start MCP server with SSE transport
webscout-mcp --transport sse --host 0.0.0.0 --port 8000

# Access the server at http://localhost:8000/sse
```

### Configuration

```bash
# Configure via environment variables
export WEBSCOUT_LOG_LEVEL=DEBUG
export WEBSCOUT_CACHE_ENABLED=true
export WEBSCOUT_CACHE_TTL=7200

# Start server
webscout-mcp
```

## Step 6: Next Steps

Now that you've learned the basics, explore these advanced topics:

1. **[Tutorial 2: Search and Fetch](02-search-and-fetch.md)** - Advanced search and content extraction
2. **[Tutorial 3: AI Processing](03-ai-processing.md)** - Deep dive into AI features
3. **[Tutorial 4: Vector Search](04-vector-search.md)** - Semantic search and RAG
4. **[Tutorial 5: Advanced Optimization](05-advanced-optimization.md)** - Performance optimization
5. **[Tutorial 6: Deployment](06-deployment.md)** - Docker and Kubernetes deployment

## Troubleshooting

### Search returns no results
- Check your internet connection
- Try a different search backend
- Check if rate limiting is triggered

### Fetch fails
- Verify the URL is correct
- Check if the website blocks bots
- Try using the headless browser fetcher

### AI processing is slow
- Reduce the input text length
- Use a faster AI model
- Enable caching for repeated requests

## Summary

In this tutorial, you learned:
- How to install webscout-mcp
- How to perform basic web searches
- How to fetch and extract web content
- How to use AI-powered content processing
- How to run the MCP server

Continue to the next tutorial to learn more advanced features!
