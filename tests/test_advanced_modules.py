"""Tests for competitor analyzer, knowledge graph, metrics, and browser fingerprint modules."""

import pytest

from webscout_mcp.browser_fingerprint import (
    BrowserFingerprint,
    FingerprintGenerator,
    generate_fingerprint,
)
from webscout_mcp.competitor_analyzer import (
    ComparisonResult,
    CompetitorAnalyzer,
    SiteMetrics,
    compare_sites,
)
from webscout_mcp.knowledge_graph import (
    Entity,
    KnowledgeGraph,
    KnowledgeGraphBuilder,
    Relationship,
    build_knowledge_graph,
)
from webscout_mcp.metrics import (
    Counter,
    Gauge,
    Histogram,
    MetricsRegistry,
    Summary,
    WebScoutMetrics,
    get_metrics,
)

# ============ Competitor Analyzer Tests ============


class TestCompetitorAnalyzer:
    """Test CompetitorAnalyzer class."""

    def test_creation(self):
        analyzer = CompetitorAnalyzer()
        assert analyzer.seo_weight == 0.35
        assert analyzer.performance_weight == 0.30

    def test_add_site(self):
        analyzer = CompetitorAnalyzer()
        site = analyzer.add_site(
            url="https://example.com",
            name="Example",
            seo_metrics={"title_length": 45, "h1_count": 1},
            performance_metrics={"html_size_kb": 50, "request_count": 10},
            content_metrics={"word_count": 500, "readability_score": 70},
        )
        assert site.url == "https://example.com"
        assert site.name == "Example"
        assert site.title_length == 45
        assert site.seo_score > 0
        assert site.overall_score > 0

    def test_compare_two_sites(self):
        analyzer = CompetitorAnalyzer()
        site1 = analyzer.add_site(
            url="https://site1.com",
            name="Site 1",
            seo_metrics={"title_length": 45, "h1_count": 1, "image_count": 5, "images_with_alt": 5},
            performance_metrics={"html_size_kb": 30, "request_count": 8, "has_gzip": True},
            content_metrics={"word_count": 800, "readability_score": 75},
        )
        site2 = analyzer.add_site(
            url="https://site2.com",
            name="Site 2",
            seo_metrics={"title_length": 100, "h1_count": 3, "image_count": 10, "images_with_alt": 2},
            performance_metrics={"html_size_kb": 200, "request_count": 30},
            content_metrics={"word_count": 100, "readability_score": 40},
        )
        result = analyzer.compare([site1, site2])
        assert result.num_sites == 2 if hasattr(result, "num_sites") else len(result.sites) == 2
        assert result.winner == "Site 1"
        assert len(result.recommendations) > 0
        assert "Site 1" in result.summary

    def test_export_comparison_table(self):
        analyzer = CompetitorAnalyzer()
        site1 = analyzer.add_site(url="https://site1.com", name="Site 1")
        site2 = analyzer.add_site(url="https://site2.com", name="Site 2")
        result = analyzer.compare([site1, site2])
        table = analyzer.export_comparison_table(result)
        assert "| Metric |" in table
        assert "Site 1" in table
        assert "Site 2" in table

    def test_compare_sites_convenience(self):
        sites_data = [
            {"url": "https://site1.com", "name": "Site 1", "seo": {"title_length": 45}},
            {"url": "https://site2.com", "name": "Site 2", "seo": {"title_length": 100}},
        ]
        result = compare_sites(sites_data)
        assert len(result.sites) == 2


# ============ Knowledge Graph Tests ============


class TestKnowledgeGraph:
    """Test KnowledgeGraphBuilder class."""

    def test_creation(self):
        builder = KnowledgeGraphBuilder()
        assert builder.min_entity_length == 2

    def test_extract_entities_dates(self):
        builder = KnowledgeGraphBuilder()
        text = "The event happened on 2023-12-25 and 2024-01-15."
        entities = builder.extract_entities(text)
        entity_types = [e.type for e in entities]
        assert "date" in entity_types

    def test_extract_entities_urls(self):
        builder = KnowledgeGraphBuilder()
        text = "Visit https://example.com for more info."
        entities = builder.extract_entities(text)
        entity_types = [e.type for e in entities]
        assert "url" in entity_types

    def test_extract_entities_technology(self):
        builder = KnowledgeGraphBuilder()
        text = "We use python and javascript for development, with docker and kubernetes."
        entities = builder.extract_entities(text)
        tech_entities = [e for e in entities if e.type == "technology"]
        assert len(tech_entities) >= 2

    def test_extract_entities_capitalized(self):
        builder = KnowledgeGraphBuilder()
        text = "John Smith works at Google Inc. in New York City."
        entities = builder.extract_entities(text)
        assert len(entities) > 0

    def test_build_graph(self):
        builder = KnowledgeGraphBuilder()
        text = """
        Python is a popular programming language. Python is used for web development
        and data science. JavaScript is another language used for web development.
        Docker and Kubernetes are used for deployment.
        """
        graph = builder.build(text)
        assert graph.num_entities > 0
        assert isinstance(graph, KnowledgeGraph)

    def test_graph_to_dict(self):
        builder = KnowledgeGraphBuilder()
        graph = builder.build("Python and JavaScript are popular languages.")
        data = graph.to_dict()
        assert "entities" in data
        assert "relationships" in data
        assert "num_entities" in data

    def test_graph_to_json(self):
        builder = KnowledgeGraphBuilder()
        graph = builder.build("Python test.")
        json_str = graph.to_json()
        assert '"entities"' in json_str

    def test_get_neighbors(self):
        builder = KnowledgeGraphBuilder()
        text = "Python and JavaScript are both used for web development together."
        graph = builder.build(text)
        if graph.entities:
            first_entity = list(graph.entities.values())[0]
            neighbors = graph.get_neighbors(first_entity.id)
            assert isinstance(neighbors, list)

    def test_calculate_centrality(self):
        builder = KnowledgeGraphBuilder()
        text = "Python is used with Docker and Kubernetes for deployment."
        graph = builder.build(text)
        centrality = builder.calculate_centrality(graph)
        assert isinstance(centrality, dict)

    def test_get_top_entities(self):
        builder = KnowledgeGraphBuilder()
        text = "Python Python Python JavaScript Docker."
        graph = builder.build(text)
        top = builder.get_top_entities(graph, top_n=3)
        assert len(top) <= 3

    def test_build_knowledge_graph_convenience(self):
        graph = build_knowledge_graph("Python and JavaScript test.")
        assert isinstance(graph, KnowledgeGraph)


# ============ Metrics Tests ============


class TestMetrics:
    """Test metrics classes."""

    def test_counter(self):
        counter = Counter("test_counter", "Test counter")
        assert counter.value == 0
        counter.inc()
        assert counter.value == 1
        counter.inc(5)
        assert counter.value == 6
        counter.reset()
        assert counter.value == 0

    def test_counter_negative_raises(self):
        counter = Counter("test")
        with pytest.raises(ValueError):
            counter.inc(-1)

    def test_gauge(self):
        gauge = Gauge("test_gauge", "Test gauge")
        assert gauge.value == 0
        gauge.set(10)
        assert gauge.value == 10
        gauge.inc()
        assert gauge.value == 11
        gauge.dec(3)
        assert gauge.value == 8

    def test_histogram(self):
        histogram = Histogram("test_hist", "Test histogram", buckets=[1, 2, 5, 10])
        histogram.observe(0.5)
        histogram.observe(1.5)
        histogram.observe(3)
        assert histogram.count == 3
        assert histogram.sum == 5.0
        assert len(histogram.bucket_counts) == 4

    def test_summary(self):
        summary = Summary("test_summary", "Test summary")
        for i in range(100):
            summary.observe(float(i))
        assert summary.count == 100
        assert summary.sum == sum(range(100))
        assert summary.quantile(0.5) > 0

    def test_registry(self):
        registry = MetricsRegistry()
        counter = registry.register_counter("test_counter", "Test")
        gauge = registry.register_gauge("test_gauge", "Test")
        assert registry.get_counter("test_counter") is counter
        assert registry.get_gauge("test_gauge") is gauge
        stats = registry.get_stats()
        assert stats["num_counters"] == 1
        assert stats["num_gauges"] == 1

    def test_registry_prometheus_format(self):
        registry = MetricsRegistry()
        counter = registry.register_counter("test_requests_total", "Total requests")
        counter.inc(5)
        output = registry.generate_prometheus_format()
        assert "# HELP test_requests_total" in output
        assert "# TYPE test_requests_total counter" in output
        assert "test_requests_total 5" in output

    def test_webscout_metrics(self):
        metrics = WebScoutMetrics()
        metrics.observe_search(duration=0.5, success=True)
        metrics.observe_fetch(duration=1.0, success=True)
        metrics.observe_cache(hit=True)
        assert metrics.search_requests.value == 1
        assert metrics.fetch_requests.value == 1
        assert metrics.cache_hits.value == 1
        assert metrics.cache_hit_rate == 1.0

    def test_get_metrics_singleton(self):
        m1 = get_metrics()
        m2 = get_metrics()
        assert m1 is m2


# ============ Browser Fingerprint Tests ============


class TestBrowserFingerprint:
    """Test FingerprintGenerator class."""

    def test_creation(self):
        generator = FingerprintGenerator()
        assert generator is not None

    def test_generate_chrome(self):
        generator = FingerprintGenerator(seed=42)
        fp = generator.generate(browser_type="chrome")
        assert fp.browser_type == "chrome"
        assert "Chrome" in fp.user_agent
        assert fp.user_agent != ""
        assert fp.fingerprint_hash != ""

    def test_generate_firefox(self):
        generator = FingerprintGenerator(seed=42)
        fp = generator.generate(browser_type="firefox")
        assert fp.browser_type == "firefox"
        assert "Firefox" in fp.user_agent

    def test_generate_safari(self):
        generator = FingerprintGenerator(seed=42)
        fp = generator.generate(browser_type="safari")
        assert fp.browser_type == "safari"
        assert "Safari" in fp.user_agent
        assert "Mac OS" in fp.platform

    def test_generate_edge(self):
        generator = FingerprintGenerator(seed=42)
        fp = generator.generate(browser_type="edge")
        assert fp.browser_type == "edge"
        assert "Edg" in fp.user_agent

    def test_generate_random(self):
        generator = FingerprintGenerator(seed=42)
        fp = generator.generate()
        assert fp.browser_type in ("chrome", "firefox", "safari", "edge")
        assert fp.user_agent != ""

    def test_fingerprint_consistency(self):
        gen1 = FingerprintGenerator(seed=42)
        gen2 = FingerprintGenerator(seed=42)
        fp1 = gen1.generate(browser_type="chrome")
        fp2 = gen2.generate(browser_type="chrome")
        assert fp1.fingerprint_hash == fp2.fingerprint_hash

    def test_fingerprint_uniqueness(self):
        generator = FingerprintGenerator()
        fps = generator.generate_consistent_set(5, browser_type="chrome")
        hashes = [fp.fingerprint_hash for fp in fps]
        assert len(set(hashes)) == len(hashes)

    def test_to_dict(self):
        generator = FingerprintGenerator(seed=42)
        fp = generator.generate(browser_type="chrome")
        data = fp.to_dict()
        assert "browser_type" in data
        assert "user_agent" in data
        assert "fingerprint_hash" in data
        assert data["webdriver"] is False

    def test_calculate_hash(self):
        fp = BrowserFingerprint(user_agent="test", platform="test")
        hash_val = fp.calculate_hash()
        assert len(hash_val) == 32  # MD5 hash length

    def test_get_stealth_scripts(self):
        generator = FingerprintGenerator(seed=42)
        fp = generator.generate(browser_type="chrome")
        scripts = generator.get_stealth_scripts(fp)
        assert "webdriver" in scripts
        assert "permissions" in scripts
        assert "languages" in scripts
        assert "navigator" in scripts["webdriver"]

    def test_generate_fingerprint_convenience(self):
        fp = generate_fingerprint(browser_type="chrome", seed=42)
        assert isinstance(fp, BrowserFingerprint)
        assert fp.browser_type == "chrome"
