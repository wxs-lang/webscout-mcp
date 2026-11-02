"""Run every MCP tool against a local fixture server and report a pass rate.

## Why this exists

Three defects in the v2.1-v2.2 range were invisible to the unit suite and only surfaced
under real invocation: a baseline that was never persisted, an ``AlertMessage`` exception
swallowed by a per-channel try/except, and a cached body that made monitoring report "no
change" forever. Every one of them had green tests.

The gap is that the tests assert on units while the failures live in the wiring. This
script drives the actual tool surface and reports a pass rate, so a regression shows up as
a number moving rather than as a user report.

## Design constraints

- **No network where it can be avoided.** 14 of the 15 tools can be exercised against a
  local HTTP server. On this machine DNS returns a fake-IP range, so anything needing real
  resolution fails for reasons unrelated to the code.
- **``web_search`` is the exception** and is reported as skipped with the reason, never
  silently dropped.
- **The server's SSRF guard rejects 127.0.0.1**, which is correct behaviour. Scenarios
  needing a local endpoint therefore drive the ``eval_services`` pipeline - the same fetch
  path the tool builds - rather than ``create_server``. Tools that are pure computation
  (knowledge graph, rag, cache) go through ``create_server`` normally.
- **Each scenario states what it proves**, so a failure names the broken behaviour.

Usage::

    python scripts/benchmark_tools.py               # human-readable summary
    python scripts/benchmark_tools.py --json out.json
    python scripts/benchmark_tools.py --strict      # exit 1 on any local failure
"""

from __future__ import annotations

import argparse
import asyncio
import http.server
import json
import pathlib
import sys
import tempfile
import threading
from dataclasses import dataclass, field
from typing import Any

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))


# --- fixture server ---------------------------------------------------

INDEX_HTML = (
    """<!doctype html>
<html><head>
<title>Fixture site for tool benchmarks</title>
<meta name="description" content="A deterministic page used to exercise the tool surface without network access.">
<link rel="canonical" href="/">
<meta property="og:title" content="Fixture">
<meta name="twitter:card" content="summary">
<script type="application/ld+json">{"@type":"Article","headline":"Fixture"}</script>
</head><body>
<h1>Fixture heading</h1>
<h2>Section one</h2>
<p>"""
    + ("Static fetching retrieves raw HTML and extracts the main content. " * 30)
    + """</p>
<h2>Section two</h2>
<p>"""
    + ("Headless browser rendering executes JavaScript before extraction. " * 20)
    + """</p>
<a href="/page2">internal link</a>
<a href="/missing">a link that 404s</a>
<img src="/a.png" alt="descriptive alt text">
</body></html>"""
)

PAGE2_HTML = (
    """<!doctype html><html><head><title>Second fixture page</title></head>
<body><h1>Second page</h1><p>"""
    + ("Another page in the same site for crawl depth. " * 15)
    + """</p><a href="/">back to index</a></body></html>"""
)

RSS_XML = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
<title>Fixture feed</title><link>http://localhost/</link><description>Feed for benchmarks</description>
<item><title>First entry</title><link>http://localhost/1</link><description>One</description></item>
<item><title>Second entry</title><link>http://localhost/2</link><description>Two</description></item>
</channel></rss>"""


class _FixtureHandler(http.server.BaseHTTPRequestHandler):
    """Serves a fixed site. State that must change between requests lives on the class."""

    price_state = {"price": 100.0}

    def do_GET(self) -> None:  # noqa: N802 - http.server naming
        path = self.path.split("?")[0]
        if path == "/":
            self._send(200, "text/html; charset=utf-8", INDEX_HTML)
        elif path == "/page2":
            self._send(200, "text/html; charset=utf-8", PAGE2_HTML)
        elif path == "/feed.xml":
            self._send(200, "application/rss+xml", RSS_XML)
        elif path == "/api/product":
            body = json.dumps({"product": {"name": "Widget", "price": self.price_state["price"]}, "stock": 5})
            self._send(200, "application/json", body)
        else:
            self._send(404, "text/plain", "not found")

    def _send(self, code: int, ctype: str, body: str) -> None:
        payload = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args: Any) -> None:
        pass


# --- result model -----------------------------------------------------


@dataclass
class ScenarioResult:
    name: str
    passed: bool
    proves: str = ""
    detail: str = ""
    error: str = ""


@dataclass
class Report:
    results: list[ScenarioResult] = field(default_factory=list)
    skipped: list[tuple[str, str]] = field(default_factory=list)

    def add(self, result: ScenarioResult) -> None:
        self.results.append(result)

    def skip(self, name: str, reason: str) -> None:
        self.skipped.append((name, reason))

    @property
    def failed(self) -> list[ScenarioResult]:
        return [r for r in self.results if not r.passed]

    def to_dict(self) -> dict:
        passed = sum(1 for r in self.results if r.passed)
        total = len(self.results)
        return {
            "total": total,
            "passed": passed,
            "failed": total - passed,
            "pass_rate": round(passed / total * 100, 1) if total else 0.0,
            "scenarios": [
                {
                    "name": r.name,
                    "passed": r.passed,
                    "proves": r.proves,
                    "detail": r.detail,
                    "error": r.error,
                }
                for r in self.results
            ],
            "skipped": [{"name": n, "reason": why} for n, why in self.skipped],
        }


def _check(name: str, proves: str, fn) -> ScenarioResult:
    """Run a synchronous scenario, capturing a failure as a result."""
    try:
        detail = fn()
        return ScenarioResult(name=name, passed=True, proves=proves, detail=str(detail or ""))
    except Exception as exc:  # noqa: BLE001 - a benchmark records failures
        return ScenarioResult(name=name, passed=False, proves=proves, error=f"{type(exc).__name__}: {exc}"[:240])


async def _check_async(name: str, proves: str, coro_factory) -> ScenarioResult:
    """Run a coroutine scenario.

    Inside `_run` there is already a running loop, so scenarios must be awaited rather
    than executed with `asyncio.run` - which was the first version's mistake and made
    fourteen of fifteen scenarios fail for a reason that had nothing to do with the code
    under test.
    """
    try:
        detail = await coro_factory()
        return ScenarioResult(name=name, passed=True, proves=proves, detail=str(detail or ""))
    except Exception as exc:  # noqa: BLE001
        return ScenarioResult(name=name, passed=False, proves=proves, error=f"{type(exc).__name__}: {exc}"[:240])


def _payload(result) -> dict:
    """Normalise whatever call_tool returned into a dict."""
    obj = result[0] if isinstance(result, tuple) else result
    content = getattr(obj, "content", obj)
    block = content[0] if isinstance(content, list) else content
    return json.loads(getattr(block, "text", str(block)))


# --- scenarios --------------------------------------------------------


async def _run(port: int, report: Report) -> None:
    import re

    from webscout_mcp.server import create_server

    server = create_server()
    base = f"http://127.0.0.1:{port}"
    workdir = pathlib.Path(tempfile.mkdtemp())

    # ---- pure computation, driven through the MCP surface ----

    async def cache_stats() -> str:
        out = _payload(await server.call_tool("cache_stats", {}))
        assert isinstance(out, dict) and out, out
        return f"keys={list(out)[:4]}"

    report.add(await _check_async("cache_stats", "returns cache counters", cache_stats))

    async def cache_clear() -> str:
        out = _payload(await server.call_tool("cache_clear", {}))
        assert isinstance(out, dict), out
        return f"keys={list(out)[:4]}"

    report.add(await _check_async("cache_clear", "clears without raising", cache_clear))

    async def search_health() -> str:
        out = _payload(await server.call_tool("search_health", {}))
        assert isinstance(out, dict) and out, out
        return f"keys={list(out)[:4]}"

    report.add(await _check_async("search_health", "reports backend health offline", search_health))

    async def knowledge_graph_text() -> str:
        out = _payload(
            await server.call_tool(
                "web_knowledge_graph",
                {"text": ("Apple Inc. is a company. Tim Cook leads Apple Inc. Microsoft competes with Apple Inc.")},
            )
        )
        stats = out.get("stats", {})
        assert stats.get("entity_count", 0) >= 2, out
        assert "Apple Inc" in {e["name"] for e in out["entities"]}, out["entities"]
        return f"entities={stats['entity_count']} rels={stats['relationship_count']}"

    report.add(
        await _check_async("web_knowledge_graph", "extracts entities and relationships offline", knowledge_graph_text)
    )

    async def rag_text() -> str:
        doc = (
            "Static fetching retrieves raw HTML quickly. "
            "Headless browser rendering executes JavaScript and costs two to six seconds. "
            "Rate limiting returns 429 and expects backoff."
        )
        out = _payload(await server.call_tool("web_rag_context", {"text": doc, "query": "browser rendering cost"}))
        assert out.get("passages"), out
        blob = json.dumps(out).lower()
        assert "six seconds" in blob or "executes javascript" in blob, out
        return f"passages={len(out['passages'])}"

    report.add(await _check_async("web_rag_context", "retrieves the answering passage offline", rag_text))

    # ---- need an endpoint; driven through the eval pipeline ----
    # The server's SSRF guard rejects 127.0.0.1 by design, so these use the same
    # fetch_service the tool builds, minus that hook.

    from webscout_mcp.eval_services import aclose_services, configure_eval_run
    from webscout_mcp.fetch_provider import FetchRequest
    from webscout_mcp.json_select import extract as json_extract
    from webscout_mcp.monitor_adapter import FetchServiceAdapter, MonitorFetchResult
    from webscout_mcp.extras.competitor_analyzer import compare_sites
    from webscout_mcp.extras.content_quality import analyze_content_quality
    from webscout_mcp.extras.monitor import MonitorConfig, WebMonitor
    from webscout_mcp.extras.performance_analyzer import analyze_performance
    from webscout_mcp.extras.seo_metrics import extract_seo_metrics

    services = configure_eval_run("benchmark-tools")
    try:
        svc = services["fetch_service"]

        async def web_fetch() -> str:
            route = await svc.fetch(FetchRequest(url=f"{base}/", extract=True, output_format="text", max_chars=20000))
            body = route.primary_response.content or ""
            assert len(body) > 500, f"only {len(body)} chars"
            assert "Static fetching" in body, body[:120]
            return f"{len(body)} chars"

        report.add(await _check_async("web_fetch", "fetches and extracts a page", web_fetch))

        async def _json_body() -> str:
            route = await svc.fetch(
                FetchRequest(
                    url=f"{base}/api/product",
                    extract=False,
                    output_format="text",
                    max_chars=100000,
                    bypass_cache=True,
                )
            )
            return route.primary_response.content or ""

        async def web_fetch_json() -> str:
            body = await _json_body()
            assert '"price"' in body, body[:120]
            return f"{len(body)} chars of JSON"

        report.add(await _check_async("web_fetch (json)", "returns a JSON body verbatim", web_fetch_json))

        async def json_selector() -> str:
            value = json_extract(await _json_body(), "json:$.product.price")
            assert value == "100.0", value
            return f"price={value}"

        report.add(await _check_async("json_select", "reduces a JSON body to one field", json_selector))

        async def monitor_detects_change() -> str:
            """The v2.1 defect: no persisted baseline meant no change was ever reported."""
            state_file = workdir / "monitor.json"
            url = f"{base}/api/product"

            async def check() -> list:
                config = MonitorConfig(history_path=str(state_file), min_change_size=1)
                monitor = WebMonitor(config=config, fetcher=FetchServiceAdapter(svc))
                # check_url is synchronous and does its own I/O once the adapter runs.
                return await asyncio.to_thread(monitor.check_url, url)

            first = await check()
            assert first == [], f"first check reported {len(first)} changes; expected a baseline"

            _FixtureHandler.price_state["price"] = 900.0
            try:
                second = await check()
            finally:
                _FixtureHandler.price_state["price"] = 100.0

            assert second, "a changed price produced no change record"
            return f"{len(second)} change(s): {second[0].change_type}"

        report.add(
            await _check_async(
                "web_monitor (persistence)",
                "a fresh monitor detects a change across checks",
                monitor_detects_change,
            )
        )

        async def monitor_quiet() -> str:
            state_file = workdir / "quiet.json"
            url = f"{base}/"

            async def check() -> list:
                config = MonitorConfig(history_path=str(state_file), min_change_size=50)
                monitor = WebMonitor(config=config, fetcher=FetchServiceAdapter(svc))
                return await asyncio.to_thread(monitor.check_url, url)

            await check()
            changes = await check()
            assert changes == [], f"identical page reported {len(changes)} changes"
            return "identical page reports nothing"

        report.add(await _check_async("web_monitor (quiet)", "an unchanged page reports nothing", monitor_quiet))

        async def monitor_filters() -> str:
            """Noise filters must suppress a churning region without hiding real content."""
            state_file = workdir / "filters.json"
            url = f"{base}/"

            def check(html: str) -> list:
                class _Fixed:
                    def fetch(self, _url, **_kw):
                        return MonitorFetchResult(content=html, html=html)

                config = MonitorConfig(history_path=str(state_file), min_change_size=2, ignore_selector=[".ad"])
                monitor = WebMonitor(config=config, fetcher=_Fixed())
                return monitor.check_url(url)

            check('<html><body><p>Stable body.</p><div class="ad">A1</div></body></html>')
            changes = check('<html><body><p>Stable body.</p><div class="ad">B2</div></body></html>')
            assert changes == [], f"ignored region still reported {len(changes)} changes"
            return "ignored region suppressed"

        report.add(
            await _check_async(
                "web_monitor (ignore_selector)", "a filtered region cannot raise a change", monitor_filters
            )
        )

        async def compare_sites_scenario() -> str:
            route = await svc.fetch(
                FetchRequest(url=f"{base}/", extract=False, output_format="html", max_chars=2_000_000)
            )
            html = route.primary_response.content or ""
            assert html, "no HTML fetched"
            plain = re.sub(r"<[^>]+>", " ", html)
            perf = analyze_performance(html, url=f"{base}/")
            quality = analyze_content_quality(plain, html=html)
            result = compare_sites(
                [
                    {
                        "url": f"{base}/",
                        "name": "fixture",
                        "seo": extract_seo_metrics(html, f"{base}/"),
                        "performance": perf.to_dict(),
                        "content": quality.to_dict(),
                        "links": {},
                    }
                ]
            ).to_dict()
            assert result["sites"], result
            site = result["sites"][0]
            assert site["seo_score"] > 50, f"seo={site['seo_score']}; the fixture has full metadata"
            return f"seo={site['seo_score']} content={site['content_score']}"

        report.add(
            await _check_async(
                "web_compare_sites",
                "scores a metadata-complete page above the SEO base",
                compare_sites_scenario,
            )
        )

        # BrokenLinkChecker installs its own SSRF guard unconditionally - correct for a
        # tool whose job is fetching arbitrary external links - so it cannot be pointed at
        # a loopback fixture. Measured rather than assumed: the call returns
        # "SSRF blocked: host 127.0.0.1 is not a public address". Reporting it as a
        # failure would blame the product for enforcing its own safety property.
        report.skip(
            "broken_links",
            "its SSRF guard rejects loopback by design; needs a public target, "
            "which this machine's fake-IP DNS cannot provide",
        )

        async def content_quality_scenario() -> str:
            route = await svc.fetch(FetchRequest(url=f"{base}/", extract=True, output_format="text", max_chars=20000))
            text = route.primary_response.content or ""
            metrics = analyze_content_quality(text)
            data = metrics.to_dict() if hasattr(metrics, "to_dict") else vars(metrics)
            assert data.get("word_count", 0) > 200, data.get("word_count")
            return f"words={data.get('word_count')}"

        report.add(await _check_async("content_quality", "grades a real page body", content_quality_scenario))

        async def rss_parse_scenario() -> str:
            route = await svc.fetch(
                FetchRequest(
                    url=f"{base}/feed.xml",
                    extract=False,
                    output_format="text",
                    max_chars=100000,
                    bypass_cache=True,
                )
            )
            body = route.primary_response.content or ""
            assert "<rss" in body, body[:120]
            from webscout_mcp.rss_parser import RSSParser

            parser = RSSParser()
            parse = getattr(parser, "parse", None) or getattr(parser, "parse_string", None)
            assert parse is not None, "RSSParser exposes no parse method"
            result = parse(body)
            entries = getattr(result, "entries", None) or []
            assert len(entries) >= 2, entries
            return f"{len(entries)} entries"

        report.add(await _check_async("rss_parse", "parses a feed into entries", rss_parse_scenario))
    finally:
        await aclose_services(services)

    # web_search is the one tool that genuinely needs the internet.
    report.skip(
        "web_search",
        "needs a live search backend; this machine's DNS returns a fake-IP range",
    )


def main() -> int:
    ap = argparse.ArgumentParser(description="Benchmark the MCP tool surface")
    ap.add_argument("--json", type=pathlib.Path, default=None, help="write the report here")
    ap.add_argument("--strict", action="store_true", help="exit 1 if any local scenario fails")
    args = ap.parse_args()

    httpd = http.server.HTTPServer(("127.0.0.1", 0), _FixtureHandler)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()

    report = Report()
    try:
        asyncio.run(_run(port, report))
    finally:
        httpd.shutdown()

    width = max((len(r.name) for r in report.results), default=20)
    print(f"\n{'scenario':<{width}}  result  proves / failure")
    print("-" * (width + 64))
    for r in report.results:
        mark = "PASS" if r.passed else "FAIL"
        note = r.proves if r.passed else r.error
        print(f"{r.name:<{width}}  {mark:<6}  {note[:98]}")
        if r.passed and r.detail:
            print(f"{'':<{width}}          -> {r.detail[:94]}")

    if report.skipped:
        print()
        for name, reason in report.skipped:
            print(f"SKIP  {name}: {reason}")

    data = report.to_dict()
    print()
    print(f"pass rate: {data['passed']}/{data['total']} ({data['pass_rate']}%)")
    if data["failed"]:
        print("failures:")
        for r in report.failed:
            print(f"  - {r.name}: {r.error}")

    if args.json:
        args.json.write_text(json.dumps(data, indent=2), encoding="utf-8")
        print(f"report written to {args.json}")

    if args.strict and data["failed"]:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
