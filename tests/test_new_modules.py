"""Tests for config models, PDF processor, and data cleaner modules."""
import os
import tempfile
import pytest
from webscout_mcp.config_models import (
    WebScoutConfig,
    ServerConfig,
    SearchConfig,
    load_config,
)
from webscout_mcp.data_cleaner import (
    TextCleaner,
    DataCleaner,
    CleaningPipeline,
    clean_data,
)


# ============ Config Models Tests ============

class TestConfigModels:
    """Test configuration models."""

    def test_default_config(self):
        config = WebScoutConfig()
        assert config.server.port == 8000
        assert config.search.max_results == 10
        assert config.crawler.max_depth == 2
        assert config.ai.backend == "ollama"
        assert config.vector_store.enabled is True
        assert config.browser.headless is True

    def test_server_config_validation(self):
        config = ServerConfig(port=8080, log_level="DEBUG")
        assert config.port == 8080
        assert config.log_level == "DEBUG"

    def test_search_config(self):
        config = SearchConfig(default_backend="duckduckgo", max_results=20)
        assert config.default_backend == "duckduckgo"
        assert config.max_results == 20

    def test_config_to_dict(self):
        config = WebScoutConfig()
        data = config.to_dict()
        assert "server" in data
        assert "search" in data
        assert "crawler" in data
        assert data["server"]["port"] == 8000

    def test_config_to_json(self):
        config = WebScoutConfig()
        json_str = config.to_json()
        assert '"port": 8000' in json_str
        assert '"max_results": 10' in json_str

    def test_config_from_dict(self):
        data = {
            "server": {"port": 9090},
            "search": {"max_results": 25},
        }
        config = WebScoutConfig.from_dict(data)
        assert config.server.port == 9090
        assert config.search.max_results == 25

    def test_list_sections(self):
        config = WebScoutConfig()
        sections = config.list_sections()
        assert "server" in sections
        assert "search" in sections
        assert "crawler" in sections
        assert "ai" in sections
        assert "vector_store" in sections

    def test_get_section(self):
        config = WebScoutConfig()
        server = config.get_section("server")
        assert server is not None
        assert server.port == 8000

    def test_get_nonexistent_section(self):
        config = WebScoutConfig()
        assert config.get_section("nonexistent") is None

    def test_from_env(self, monkeypatch):
        monkeypatch.setenv("WEBSCOUT_SEARCH_MAX_RESULTS", "20")
        monkeypatch.setenv("WEBSCOUT_SERVER_PORT", "9090")
        config = WebScoutConfig.from_env()
        assert config.search.max_results == 20
        assert config.server.port == 9090

    def test_load_config_from_file(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write('{"server": {"port": 8888}}')
            f.flush()
            config = load_config(f.name)
            assert config.server.port == 8888
        os.unlink(f.name)

    def test_load_config_nonexistent_file(self):
        config = load_config("/nonexistent/path/config.json")
        assert config.server.port == 8000  # Default


# ============ Text Cleaner Tests ============

class TestTextCleaner:
    """Test TextCleaner class."""

    def test_remove_html_tags(self):
        assert TextCleaner.remove_html_tags("<p>Hello <b>World</b></p>") == "Hello World"

    def test_remove_html_tags_empty(self):
        assert TextCleaner.remove_html_tags("") == ""

    def test_decode_html_entities(self):
        assert TextCleaner.decode_html_entities("Tom &amp; Jerry") == "Tom & Jerry"
        assert TextCleaner.decode_html_entities("&lt;script&gt;") == "<script>"

    def test_normalize_whitespace(self):
        assert TextCleaner.normalize_whitespace("  hello   world  ") == "hello world"
        assert TextCleaner.normalize_whitespace("hello\n\nworld") == "hello world"

    def test_remove_special_chars(self):
        result = TextCleaner.remove_special_chars("Hello, World! 123")
        assert "Hello" in result
        assert "World" in result
        assert "123" in result

    def test_normalize_unicode(self):
        # Fullwidth to halfwidth
        result = TextCleaner.normalize_unicode("Ｈｅｌｌｏ")
        assert result == "Hello"

    def test_to_lowercase(self):
        assert TextCleaner.to_lowercase("HELLO World") == "hello world"

    def test_to_uppercase(self):
        assert TextCleaner.to_uppercase("hello World") == "HELLO WORLD"

    def test_remove_urls(self):
        result = TextCleaner.remove_urls("Visit https://example.com for more")
        assert "https://example.com" not in result
        assert "Visit" in result

    def test_remove_emails(self):
        result = TextCleaner.remove_emails("Contact test@example.com for info")
        assert "test@example.com" not in result
        assert "Contact" in result

    def test_truncate(self):
        assert TextCleaner.truncate("Hello World", 8) == "Hello..."
        assert TextCleaner.truncate("Hi", 10) == "Hi"

    def test_clean_full(self):
        html = "<p>  Hello   &amp;   World  </p>"
        result = TextCleaner.clean_full(html)
        assert result == "Hello & World"


# ============ Data Cleaner Tests ============

class TestDataCleaner:
    """Test DataCleaner class."""

    @pytest.fixture
    def sample_records(self):
        return [
            {"title": "  Hello  <b>World</b>  ", "url": "https://example.com/1", "content": "Test 1"},
            {"title": "Another Page", "url": "https://example.com/2", "content": "Test 2"},
            {"title": "  Hello  <b>World</b>  ", "url": "https://example.com/1", "content": "Duplicate"},
            {"title": "", "url": "", "content": ""},  # Empty record
        ]

    def test_creation(self):
        cleaner = DataCleaner(text_fields=["title"])
        assert cleaner.text_fields == ["title"]

    def test_clean_record(self):
        cleaner = DataCleaner(text_fields=["title"])
        record = {"title": "  <b>Hello</b>  World  ", "url": "https://example.com"}
        cleaned = cleaner.clean_record(record)
        assert cleaned is not None
        assert cleaned["title"] == "Hello World"

    def test_clean_record_required_field_missing(self):
        cleaner = DataCleaner(required_fields=["url"])
        record = {"title": "No URL"}
        assert cleaner.clean_record(record) is None

    def test_clean_batch(self, sample_records):
        cleaner = DataCleaner(
            text_fields=["title"],
            required_fields=["url"],
            dedup_fields=["url"],
        )
        cleaned, result = cleaner.clean_batch(sample_records)
        assert result.original_count == 4
        assert result.removed_count >= 2  # Empty + duplicate
        assert result.cleaned_count <= 2
        assert all("url" in r for r in cleaned)

    def test_clean_batch_modified_count(self, sample_records):
        cleaner = DataCleaner(text_fields=["title"])
        cleaned, result = cleaner.clean_batch(sample_records)
        assert result.modified_count > 0  # At least some records modified

    def test_deduplication(self):
        cleaner = DataCleaner(dedup_fields=["id"])
        records = [
            {"id": "1", "name": "First"},
            {"id": "1", "name": "Duplicate"},
            {"id": "2", "name": "Second"},
        ]
        cleaned, result = cleaner.clean_batch(records)
        assert len(cleaned) == 2
        assert result.removed_count == 1

    def test_remove_empty_records(self):
        cleaner = DataCleaner(remove_empty=True)
        records = [
            {"name": "Valid"},
            {"name": ""},
            {"name": None},
        ]
        cleaned, result = cleaner.clean_batch(records)
        assert len(cleaned) == 1

    def test_reset(self):
        cleaner = DataCleaner(dedup_fields=["id"])
        cleaner.clean_batch([{"id": "1"}])
        cleaner.reset()
        # After reset, same ID should be allowed
        cleaned, _ = cleaner.clean_batch([{"id": "1"}])
        assert len(cleaned) == 1

    def test_max_text_length(self):
        cleaner = DataCleaner(text_fields=["content"], max_text_length=10)
        record = {"content": "A" * 100}
        cleaned = cleaner.clean_record(record)
        assert len(cleaned["content"]) <= 10


# ============ Cleaning Pipeline Tests ============

class TestCleaningPipeline:
    """Test CleaningPipeline class."""

    def test_creation(self):
        pipeline = CleaningPipeline(name="test")
        assert pipeline.name == "test"
        assert len(pipeline) == 0

    def test_add_step(self):
        pipeline = CleaningPipeline()
        pipeline.add_step("uppercase", lambda r: {k: v.upper() if isinstance(v, str) else v for k, v in r.items()})
        assert len(pipeline) == 1
        assert "uppercase" in pipeline.steps

    def test_add_text_cleaner(self):
        pipeline = CleaningPipeline()
        pipeline.add_text_cleaner(["title"])
        assert len(pipeline) == 1

    def test_add_field_validator(self):
        pipeline = CleaningPipeline()
        pipeline.add_field_validator("age", lambda v: v >= 18)
        records = [{"name": "Adult", "age": 25}, {"name": "Child", "age": 15}]
        processed, result = pipeline.process(records)
        assert len(processed) == 1
        assert processed[0]["name"] == "Adult"

    def test_add_field_transformer(self):
        pipeline = CleaningPipeline()
        pipeline.add_field_transformer("count", lambda v: v * 2)
        records = [{"count": 5}]
        processed, _ = pipeline.process(records)
        assert processed[0]["count"] == 10

    def test_add_deduplicator(self):
        pipeline = CleaningPipeline()
        pipeline.add_deduplicator(["id"])
        records = [{"id": "1", "name": "First"}, {"id": "1", "name": "Dup"}, {"id": "2", "name": "Second"}]
        processed, result = pipeline.process(records)
        assert len(processed) == 2
        assert result.removed_count == 1

    def test_add_filter(self):
        pipeline = CleaningPipeline()
        pipeline.add_filter(lambda r: r.get("active", False))
        records = [{"name": "Active", "active": True}, {"name": "Inactive", "active": False}]
        processed, _ = pipeline.process(records)
        assert len(processed) == 1
        assert processed[0]["name"] == "Active"

    def test_chained_pipeline(self):
        pipeline = CleaningPipeline()
        (pipeline
         .add_text_cleaner(["name"])
         .add_field_validator("age", lambda v: v >= 18)
         .add_deduplicator(["email"]))

        records = [
            {"name": "  <b>John</b>  ", "age": 25, "email": "john@test.com"},
            {"name": "Jane", "age": 17, "email": "jane@test.com"},  # Too young
            {"name": "John Dup", "age": 30, "email": "john@test.com"},  # Duplicate email
        ]
        processed, result = pipeline.process(records)
        assert len(processed) == 1
        assert processed[0]["name"] == "John"
        assert result.removed_count == 2

    def test_pipeline_stats(self):
        pipeline = CleaningPipeline()
        pipeline.add_filter(lambda r: r.get("valid", False))
        records = [{"valid": True}, {"valid": False}]
        processed, result = pipeline.process(records)
        assert result.original_count == 2
        assert result.cleaned_count == 1
        assert result.removed_count == 1
        assert "retention_rate" in result.stats


# ============ Convenience Function Tests ============

class TestConvenienceFunctions:
    """Test convenience functions."""

    def test_clean_data(self):
        records = [
            {"title": "  <b>Hello</b>  ", "url": "https://example.com/1"},
            {"title": "World", "url": "https://example.com/2"},
        ]
        cleaned, result = clean_data(records, text_fields=["title"])
        assert result.original_count == 2
        assert cleaned[0]["title"] == "Hello"
