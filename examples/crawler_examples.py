"""
Crawler usage examples for webscout-mcp Python API.

This file demonstrates:
- Basic crawling
- Crawling with delay and retries
- Crawling configuration options
- Exporting crawl results

Run with: python examples/crawler_examples.py
"""
import asyncio
import json
from webscout_mcp import Config, Fetcher, Crawler, Exporter


async def example_basic_crawl():
    """Example: Basic website crawl."""
    print("=" * 60)
    print("Example: Basic website crawl")
    print("=" * 60)

    config = Config.from_env()
    config.ensure_dirs()

    fetcher = Fetcher(config)
    crawler = Crawler(config, fetcher)

    result = await crawler.crawl(
        seed_url="https://example.com",
        max_depth=1,
        max_pages=5,
        same_domain_only=True,
        extract=True,
    )

    print(f"Seed URL: {result.seed_url}")
    print(f"Pages crawled: {result.pages_crawled}")
    print(f"Links found: {result.links_found}")
    print(f"Skipped by robots.txt: {result.skipped_robots}")
    print(f"Errors: {len(result.errors)}")
    print()

    for i, page in enumerate(result.pages[:3]):
        print(f"Page {i+1}: {page.title}")
        print(f"  URL: {page.url}")
        print(f"  Status: {page.status_code}")
        print(f"  Content length: {len(page.content)} chars")
        print()

    await fetcher.close()


async def example_reliable_crawl():
    """Example: Crawl with delay and retries for reliability."""
    print("=" * 60)
    print("Example: Reliable crawl with delay and retries")
    print("=" * 60)

    config = Config.from_env()
    config.ensure_dirs()

    fetcher = Fetcher(config)
    crawler = Crawler(config, fetcher)

    # Use delay and retries for sites with anti-bot protection
    result = await crawler.crawl(
        seed_url="https://example.com",
        max_depth=1,
        max_pages=3,
        same_domain_only=True,
        extract=True,
        concurrency=2,  # Lower concurrency
        delay=1.0,  # 1 second base delay (randomized 0.5-1.5s)
        max_retries=3,  # Retry up to 3 times on transient failures
    )

    print(f"Pages crawled: {result.pages_crawled}")
    print(f"Retries: {result.retries}")
    print(f"Avg response time: {result.avg_response_time:.2f}s")
    print(f"Errors: {len(result.errors)}")
    print()

    if result.errors:
        print("Errors:")
        for err in result.errors[:3]:
            print(f"  - {err['url']}: {err['error']} (type: {err.get('type', 'unknown')})")
        print()

    await fetcher.close()


async def example_export_crawl():
    """Example: Export crawl results to different formats."""
    print("=" * 60)
    print("Example: Export crawl results")
    print("=" * 60)

    config = Config.from_env()
    config.ensure_dirs()

    fetcher = Fetcher(config)
    crawler = Crawler(config, fetcher)

    result = await crawler.crawl(
        seed_url="https://example.com",
        max_depth=1,
        max_pages=3,
        extract=True,
    )

    # Convert to dict for export
    crawl_data = result.to_dict()

    # Export to JSON
    exporter = Exporter()
    json_output = exporter.to_json(crawl_data)
    print(f"JSON output ({len(json_output)} chars):")
    print(json_output[:500] + "...")
    print()

    # Export to CSV
    try:
        csv_output = exporter.to_csv(crawl_data.get("pages", []))
        print(f"CSV output ({len(csv_output)} chars):")
        print(csv_output[:500] + "...")
    except Exception as e:
        print(f"CSV export note: {e}")
    print()

    # Export to Markdown
    try:
        md_output = exporter.to_markdown(crawl_data.get("pages", []))
        print(f"Markdown output ({len(md_output)} chars):")
        print(md_output[:500] + "...")
    except Exception as e:
        print(f"Markdown export note: {e}")
    print()

    await fetcher.close()


async def example_crawler_config():
    """Example: Crawler configuration via environment variables."""
    print("=" * 60)
    print("Example: Crawler configuration options")
    print("=" * 60)

    config = Config.from_env()

    print("Current crawler configuration:")
    print(f"  max_depth: {config.crawler_max_depth}")
    print(f"  max_pages: {config.crawler_max_pages}")
    print(f"  same_domain_only: {config.crawler_same_domain_only}")
    print(f"  concurrency: {config.crawler_concurrency}")
    print(f"  delay: {config.crawler_delay}s")
    print(f"  max_retries: {config.crawler_max_retries}")
    print(f"  respect_robots: {config.respect_robots}")
    print()

    print("Environment variables to configure:")
    print("  WEBSCOUT_CRAWLER_MAX_DEPTH=2")
    print("  WEBSCOUT_CRAWLER_MAX_PAGES=20")
    print("  WEBSCOUT_CRAWLER_CONCURRENCY=5")
    print("  WEBSCOUT_CRAWLER_DELAY=0.0")
    print("  WEBSCOUT_CRAWLER_MAX_RETRIES=2")
    print("  WEBSCOUT_RESPECT_ROBOTS=true")
    print()


async def main():
    """Run all examples."""
    try:
        await example_basic_crawl()
        await example_reliable_crawl()
        await example_export_crawl()
        await example_crawler_config()
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        print("Note: Some examples require network access.")


if __name__ == "__main__":
    asyncio.run(main())
