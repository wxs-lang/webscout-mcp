"""
Tests for config_models module - Pydantic configuration models.

Tests main config model, serialization, and loading.
"""

import pytest
import sys
import os
import json
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from webscout_mcp.config_models import (
    WebScoutConfig,
    load_config,
)


class TestWebScoutConfig:
    """Tests for WebScoutConfig (main config)."""

    def test_default_creation(self):
        """Test default WebScoutConfig creation."""
        config = WebScoutConfig()
        assert config is not None

    def test_nested_config_access(self):
        """Test nested config access."""
        config = WebScoutConfig()
        # Access nested configs - they should exist
        assert hasattr(config, "server")
        assert hasattr(config, "cache")
        assert hasattr(config, "search")
        assert hasattr(config, "crawler")
        assert hasattr(config, "ai")
        assert hasattr(config, "vector_store")
        assert hasattr(config, "browser")
        assert hasattr(config, "monitor")
        assert hasattr(config, "ssrf")
        assert hasattr(config, "rate_limit")

    def test_serialization(self):
        """Test WebScoutConfig serialization."""
        config = WebScoutConfig()
        data = config.model_dump()
        assert isinstance(data, dict)
        assert "server" in data
        assert "cache" in data
        assert "search" in data
        assert "crawler" in data
        assert "ai" in data
        assert "vector_store" in data
        assert "browser" in data
        assert "monitor" in data
        assert "ssrf" in data
        assert "rate_limit" in data

    def test_json_serialization(self):
        """Test WebScoutConfig JSON serialization."""
        config = WebScoutConfig()
        json_str = config.model_dump_json()
        assert isinstance(json_str, str)
        data = json.loads(json_str)
        assert isinstance(data, dict)
        assert "server" in data

    def test_json_deserialization(self):
        """Test WebScoutConfig JSON deserialization."""
        config = WebScoutConfig()
        json_str = config.model_dump_json()
        loaded_config = WebScoutConfig.model_validate_json(json_str)
        assert loaded_config is not None
        assert isinstance(loaded_config, WebScoutConfig)

    def test_dict_deserialization(self):
        """Test WebScoutConfig dict deserialization."""
        config = WebScoutConfig()
        data = config.model_dump()
        loaded_config = WebScoutConfig.model_validate(data)
        assert loaded_config is not None
        assert isinstance(loaded_config, WebScoutConfig)

    def test_config_equality(self):
        """Test config equality after serialization roundtrip."""
        config = WebScoutConfig()
        json_str = config.model_dump_json()
        loaded_config = WebScoutConfig.model_validate_json(json_str)
        # Should be equal after roundtrip
        assert config.model_dump() == loaded_config.model_dump()

    def test_nested_config_types(self):
        """Test that nested configs are proper types."""
        config = WebScoutConfig()
        # Each nested config should be a Pydantic model
        assert hasattr(config.server, "model_dump")
        assert hasattr(config.cache, "model_dump")
        assert hasattr(config.search, "model_dump")
        assert hasattr(config.crawler, "model_dump")
        assert hasattr(config.ai, "model_dump")
        assert hasattr(config.vector_store, "model_dump")
        assert hasattr(config.browser, "model_dump")
        assert hasattr(config.monitor, "model_dump")
        assert hasattr(config.ssrf, "model_dump")
        assert hasattr(config.rate_limit, "model_dump")

    def test_server_config_fields(self):
        """Test server config has expected fields."""
        config = WebScoutConfig()
        server_data = config.server.model_dump()
        # Server config should have some fields
        assert len(server_data) > 0

    def test_cache_config_fields(self):
        """Test cache config has expected fields."""
        config = WebScoutConfig()
        cache_data = config.cache.model_dump()
        assert len(cache_data) > 0

    def test_search_config_fields(self):
        """Test search config has expected fields."""
        config = WebScoutConfig()
        search_data = config.search.model_dump()
        assert len(search_data) > 0

    def test_crawler_config_fields(self):
        """Test crawler config has expected fields."""
        config = WebScoutConfig()
        crawler_data = config.crawler.model_dump()
        assert len(crawler_data) > 0

    def test_ai_config_fields(self):
        """Test AI config has expected fields."""
        config = WebScoutConfig()
        ai_data = config.ai.model_dump()
        assert len(ai_data) > 0

    def test_vector_store_config_fields(self):
        """Test vector store config has expected fields."""
        config = WebScoutConfig()
        vs_data = config.vector_store.model_dump()
        assert len(vs_data) > 0

    def test_browser_config_fields(self):
        """Test browser config has expected fields."""
        config = WebScoutConfig()
        browser_data = config.browser.model_dump()
        assert len(browser_data) > 0

    def test_monitor_config_fields(self):
        """Test monitor config has expected fields."""
        config = WebScoutConfig()
        monitor_data = config.monitor.model_dump()
        assert len(monitor_data) > 0

    def test_ssrf_config_fields(self):
        """Test SSRF config has expected fields."""
        config = WebScoutConfig()
        ssrf_data = config.ssrf.model_dump()
        assert len(ssrf_data) > 0

    def test_rate_limit_config_fields(self):
        """Test rate limit config has expected fields."""
        config = WebScoutConfig()
        rl_data = config.rate_limit.model_dump()
        assert len(rl_data) > 0


class TestLoadConfig:
    """Tests for load_config function."""

    def test_load_default_config(self):
        """Test loading default config (no file)."""
        config = load_config()
        assert isinstance(config, WebScoutConfig)

    def test_load_config_from_json_file(self):
        """Test loading config from JSON file."""
        config = WebScoutConfig()
        json_str = config.model_dump_json()

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write(json_str)
            temp_path = f.name

        try:
            loaded_config = load_config(temp_path)
            assert isinstance(loaded_config, WebScoutConfig)
            # Should be equal after roundtrip
            assert config.model_dump() == loaded_config.model_dump()
        finally:
            os.unlink(temp_path)

    def test_load_config_from_yaml_file(self):
        """Test loading config from YAML file (if yaml available)."""
        try:
            import yaml
            config = WebScoutConfig()
            data = config.model_dump()

            with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
                yaml.dump(data, f)
                temp_path = f.name

            try:
                loaded_config = load_config(temp_path)
                assert isinstance(loaded_config, WebScoutConfig)
            finally:
                os.unlink(temp_path)
        except ImportError:
            pytest.skip("PyYAML not installed")

    def test_load_config_nonexistent_file(self):
        """Test loading config from nonexistent file (should use defaults)."""
        config = load_config("/nonexistent/path/config.json")
        assert isinstance(config, WebScoutConfig)

    def test_load_config_empty_string(self):
        """Test loading config with empty string path."""
        config = load_config("")
        assert isinstance(config, WebScoutConfig)

    def test_load_config_none_path(self):
        """Test loading config with None path."""
        config = load_config(None)
        assert isinstance(config, WebScoutConfig)

    def test_load_config_invalid_json(self):
        """Test loading config from invalid JSON file (should use defaults)."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write("invalid json content")
            temp_path = f.name

        try:
            config = load_config(temp_path)
            assert isinstance(config, WebScoutConfig)
        finally:
            os.unlink(temp_path)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
