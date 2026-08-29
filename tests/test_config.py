"""Tests for configuration management (config module)."""

from webscout_mcp.config import Config


class TestConfigDefaults:
    """Test Config default values."""

    def test_default_cache_ttl(self):
        config = Config()
        assert config.cache_ttl == 7200

    def test_default_request_timeout(self):
        config = Config()
        assert config.request_timeout == 15.0

    def test_default_max_retries(self):
        config = Config()
        assert config.max_retries == 3

    def test_default_search_backends(self):
        config = Config()
        assert config.search_backends == ["bing", "duckduckgo"]

    def test_default_crawler_concurrency(self):
        config = Config()
        assert config.crawler_concurrency == 5


class TestConfigFromEnv:
    """Test Config from environment variables."""

    def test_from_env_cache_ttl(self, monkeypatch):
        monkeypatch.setenv("WEBSCOUT_CACHE_TTL", "3600")
        config = Config.from_env()
        assert config.cache_ttl == 3600

    def test_from_env_request_timeout(self, monkeypatch):
        monkeypatch.setenv("WEBSCOUT_REQUEST_TIMEOUT", "30.0")
        config = Config.from_env()
        assert config.request_timeout == 30.0

    def test_from_env_search_backends(self, monkeypatch):
        monkeypatch.setenv("WEBSCOUT_SEARCH_BACKENDS", "google,bing")
        config = Config.from_env()
        assert config.search_backends == ["google", "bing"]

    def test_from_env_respect_robots(self, monkeypatch):
        monkeypatch.setenv("WEBSCOUT_RESPECT_ROBOTS", "false")
        config = Config.from_env()
        assert config.respect_robots is False


class TestConfigReload:
    """Test Config hot-reload functionality."""

    def test_reload_updates_values(self, monkeypatch):
        config = Config()
        original_ttl = config.cache_ttl

        monkeypatch.setenv("WEBSCOUT_CACHE_TTL", "1800")
        config.reload()

        assert config.cache_ttl == 1800
        assert config.cache_ttl != original_ttl

    def test_reload_returns_self(self):
        config = Config()
        result = config.reload()
        assert result is config

    def test_reload_multiple_values(self, monkeypatch):
        config = Config()

        monkeypatch.setenv("WEBSCOUT_CACHE_TTL", "1800")
        monkeypatch.setenv("WEBSCOUT_REQUEST_TIMEOUT", "45.0")
        monkeypatch.setenv("WEBSCOUT_MAX_RETRIES", "5")
        config.reload()

        assert config.cache_ttl == 1800
        assert config.request_timeout == 45.0
        assert config.max_retries == 5


class TestConfigToDict:
    """Test Config to_dict method."""

    def test_to_dict_returns_dict(self):
        config = Config()
        result = config.to_dict()
        assert isinstance(result, dict)

    def test_to_dict_contains_keys(self):
        config = Config()
        result = config.to_dict()
        assert "cache_ttl" in result
        assert "request_timeout" in result
        assert "max_retries" in result
        assert "search_backends" in result

    def test_to_dict_path_converted_to_string(self):
        config = Config()
        result = config.to_dict()
        assert isinstance(result["cache_dir"], str)

    def test_to_dict_values_match_config(self):
        config = Config(cache_ttl=9999, request_timeout=99.0)
        result = config.to_dict()
        assert result["cache_ttl"] == 9999
        assert result["request_timeout"] == 99.0


class TestConfigEnsureDirs:
    """Test Config ensure_dirs method."""

    def test_ensure_dirs_creates_directory(self, tmp_path):
        config = Config(cache_dir=tmp_path / "test_cache")
        assert not (tmp_path / "test_cache").exists()

        config.ensure_dirs()

        assert (tmp_path / "test_cache").exists()
        assert (tmp_path / "test_cache").is_dir()

    def test_ensure_dirs_idempotent(self, tmp_path):
        config = Config(cache_dir=tmp_path / "test_cache")
        config.ensure_dirs()
        config.ensure_dirs()  # Should not raise

        assert (tmp_path / "test_cache").exists()
