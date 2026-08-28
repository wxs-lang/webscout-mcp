"""
Basic usage examples for webscout-mcp Python API.

This file demonstrates the core functionality:
- Fetching a web page
- Searching the web
- Extracting structured data
- Basic crawling

Run with: python examples/basic_usage.py
"""

import asyncio

from webscout_mcp import Config, Extractor, Fetcher, SearchEngine


async def example_fetch():
    """Example: Fetch a web page and extract content."""
    print("=" * 60)
    print("Example: Fetch a web page")
    print("=" * 60)

    config = Config.from_env()
    config.ensure_dirs()

    fetcher = Fetcher(config)
    result = await fetcher.fetch("https://example.com", extract=True)

    print(f"URL: {result.url}")
    print(f"Status: {result.status_code}")
    print(f"Title: {result.title}")
    print(f"Content type: {result.content_type}")
    print(f"Extracted: {result.extracted}")
    print(f"Content (first 200 chars):\n{result.content[:200]}...")
    print()

    await fetcher.close()


async def example_search():
    """Example: Search the web."""
    print("=" * 60)
    print("Example: Search the web")
    print("=" * 60)

    config = Config.from_env()
    config.ensure_dirs()

    # Basic search (single backend, automatic failover)
    search = SearchEngine(config)
    results = await search.search("python async programming", max_results=5)

    print(f"Query: python async programming")
    print(f"Results: {len(results)}")
    print()

    for r in results:
        print(f"{r.position}. [{r.backend}] (score: {r.relevance_score:.1f}) {r.title}")
        print(f"   URL: {r.url}")
        print(f"   Snippet: {r.snippet[:100]}...")
        print()

    await search.close()

    # Multi-backend merged search (higher quality)
    print("-" * 60)
    print("Multi-backend merged search:")
    print("-" * 60)

    search_merged = SearchEngine(config, merge_backends=True)
    results_merged = await search_merged.search("python async programming", max_results=5)

    for r in results_merged:
        print(f"{r.position}. [{r.backend}] (score: {r.relevance_score:.1f}) {r.title}")

    await search_merged.close()
    print()


async def example_extract():
    """Example: Extract structured data from a page."""
    print("=" * 60)
    print("Example: Extract structured data")
    print("=" * 60)

    config = Config.from_env()
    config.ensure_dirs()

    fetcher = Fetcher(config)
    page = await fetcher.fetch("https://example.com", extract=False)

    if page.raw_html:
        extractor = Extractor()
        rules = [
            {"name": "title", "selector": "h1", "multiple": False},
            {"name": "paragraphs", "selector": "p", "multiple": True},
            {"name": "links", "selector": "a", "attribute": "href", "multiple": True},
        ]
        results = extractor.extract(page.raw_html, rules)
        print(f"Title: {results.get('title', 'N/A')}")
        print(f"Paragraphs found: {len(results.get('paragraphs', []))}")
        print(f"Links found: {len(results.get('links', []))}")
        if results.get("links"):
            print(f"First link: {results['links'][0]}")

    await fetcher.close()
    print()


async def main():
    """Run all examples."""
    try:
        await example_fetch()
        await example_search()
        await example_extract()
    except Exception as e:
        print(f"Error: {e}")
        print("Note: Some examples require network access.")


if __name__ == "__main__":
    asyncio.run(main())
