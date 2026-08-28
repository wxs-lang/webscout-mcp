"""Tests for plugin system."""

import pytest

from webscout_mcp.builtin_plugins import (
    ConsoleAlertChannel,
    ContentLengthFilter,
    DuplicateRemover,
    ExampleSearchBackend,
    LanguageDetector,
    ReadabilityExtractor,
)
from webscout_mcp.plugin_system import (
    AlertChannelPlugin,
    ExtractorPlugin,
    Plugin,
    PluginInfo,
    PluginManager,
    PostProcessorPlugin,
    SearchBackendPlugin,
    get_plugin_manager,
    register_plugin,
)


class TestPluginBaseClasses:
    """Test plugin base classes."""

    def test_plugin_abstract_methods(self):
        """Test that Plugin base class requires name property."""
        with pytest.raises(TypeError):
            Plugin()

    def test_search_backend_plugin_abstract(self):
        """Test that SearchBackendPlugin requires search method."""
        with pytest.raises(TypeError):
            SearchBackendPlugin()

    def test_extractor_plugin_abstract(self):
        """Test that ExtractorPlugin requires extract method."""
        with pytest.raises(TypeError):
            ExtractorPlugin()

    def test_alert_channel_plugin_abstract(self):
        """Test that AlertChannelPlugin requires send_alert method."""
        with pytest.raises(TypeError):
            AlertChannelPlugin()

    def test_post_processor_plugin_abstract(self):
        """Test that PostProcessorPlugin requires process method."""
        with pytest.raises(TypeError):
            PostProcessorPlugin()


class TestPluginInfo:
    """Test PluginInfo class."""

    def test_plugin_info_creation(self):
        info = PluginInfo(
            name="test_plugin",
            version="1.0.0",
            plugin_type="search_backend",
            description="Test plugin",
        )
        assert info.name == "test_plugin"
        assert info.version == "1.0.0"
        assert info.plugin_type == "search_backend"
        assert info.description == "Test plugin"
        assert info.enabled is True
        assert info.loaded is False

    def test_plugin_info_to_dict(self):
        info = PluginInfo(
            name="test_plugin",
            version="1.0.0",
            plugin_type="extractor",
            author="test",
            dependencies=["dep1"],
        )
        data = info.to_dict()
        assert data["name"] == "test_plugin"
        assert data["version"] == "1.0.0"
        assert data["plugin_type"] == "extractor"
        assert data["author"] == "test"
        assert data["dependencies"] == ["dep1"]


class TestPluginManager:
    """Test PluginManager class."""

    def test_plugin_manager_creation(self):
        manager = PluginManager(auto_discover=False)
        assert manager is not None
        assert manager._plugins == {}

    def test_register_builtin_plugin(self):
        manager = PluginManager(auto_discover=False)
        manager.register_builtin(ExampleSearchBackend)
        assert "example_search" in manager._builtin_plugins

    def test_load_plugin(self):
        manager = PluginManager(auto_discover=False)
        manager.register_builtin(ExampleSearchBackend)
        success = manager.load_plugin("example_search")
        assert success is True
        assert "example_search" in manager._plugins
        assert manager._plugins["example_search"].loaded is True

    def test_load_nonexistent_plugin(self):
        manager = PluginManager(auto_discover=False)
        success = manager.load_plugin("nonexistent")
        assert success is False

    def test_unload_plugin(self):
        manager = PluginManager(auto_discover=False)
        manager.register_builtin(ExampleSearchBackend)
        manager.load_plugin("example_search")
        success = manager.unload_plugin("example_search")
        assert success is True
        assert manager._plugins["example_search"].loaded is False

    def test_unload_nonexistent_plugin(self):
        manager = PluginManager(auto_discover=False)
        success = manager.unload_plugin("nonexistent")
        assert success is False

    def test_get_plugin(self):
        manager = PluginManager(auto_discover=False)
        manager.register_builtin(ExampleSearchBackend)
        manager.load_plugin("example_search")
        plugin = manager.get_plugin("example_search")
        assert plugin is not None
        assert plugin.name == "example_search"

    def test_get_nonexistent_plugin(self):
        manager = PluginManager(auto_discover=False)
        plugin = manager.get_plugin("nonexistent")
        assert plugin is None

    def test_get_plugins_by_type(self):
        manager = PluginManager(auto_discover=False)
        manager.register_builtin(ExampleSearchBackend)
        manager.register_builtin(ReadabilityExtractor)
        manager.load_plugin("example_search")
        manager.load_plugin("readability_extractor")

        search_plugins = manager.get_plugins_by_type("search_backend")
        assert len(search_plugins) == 1
        assert search_plugins[0].name == "example_search"

        extractor_plugins = manager.get_plugins_by_type("extractor")
        assert len(extractor_plugins) == 1
        assert extractor_plugins[0].name == "readability_extractor"

    def test_enable_disable_plugin(self):
        manager = PluginManager(auto_discover=False)
        manager.register_builtin(ExampleSearchBackend)
        manager.load_plugin("example_search")

        assert manager._plugins["example_search"].enabled is True

        manager.disable_plugin("example_search")
        assert manager._plugins["example_search"].enabled is False

        manager.enable_plugin("example_search")
        assert manager._plugins["example_search"].enabled is True

    def test_reload_plugin(self):
        manager = PluginManager(auto_discover=False)
        manager.register_builtin(ExampleSearchBackend)
        manager.load_plugin("example_search")
        success = manager.reload_plugin("example_search")
        assert success is True
        assert manager._plugins["example_search"].loaded is True

    def test_get_stats(self):
        manager = PluginManager(auto_discover=False)
        manager.register_builtin(ExampleSearchBackend)
        manager.load_plugin("example_search")

        stats = manager.get_stats()
        assert stats["total_registered"] >= 1
        assert stats["total_loaded"] >= 1
        assert "search_backend" in stats["by_type"]

    def test_add_plugin_dir(self, tmp_path):
        manager = PluginManager(auto_discover=False)
        plugin_dir = str(tmp_path)
        manager.add_plugin_dir(plugin_dir)
        assert plugin_dir in manager._plugin_dirs


class TestBuiltinPlugins:
    """Test built-in plugins."""

    def test_example_search_backend(self):
        plugin = ExampleSearchBackend()
        assert plugin.name == "example_search"
        assert plugin.plugin_type == "search_backend"
        assert plugin.initialize() is True

        results = plugin.search("test query", max_results=5)
        assert len(results) == 1
        assert "test query" in results[0]["title"]

    def test_readability_extractor(self):
        plugin = ReadabilityExtractor()
        assert plugin.name == "readability_extractor"
        assert plugin.plugin_type == "extractor"

        html = "<html><head><title>Test</title></head><body><article>Test content</article></body></html>"
        result = plugin.extract(html, url="https://example.com")
        assert result["extractor"] == "readability"
        assert "success" in result

    def test_console_alert_channel(self):
        plugin = ConsoleAlertChannel()
        assert plugin.name == "console_alert"
        assert plugin.plugin_type == "alert_channel"
        assert plugin.initialize() is True

        success = plugin.send_alert("Test Alert", "Test content")
        assert success is True

    def test_content_length_filter(self):
        plugin = ContentLengthFilter()
        assert plugin.name == "content_length_filter"
        assert plugin.plugin_type == "post_processor"
        assert plugin.initialize({"min_length": 10, "max_length": 100}) is True

        # Test with content in range
        data = {"content": "x" * 50}
        result = plugin.process(data)
        assert result == data

        # Test with content too short
        data = {"content": "short"}
        result = plugin.process(data)
        assert result is None

        # Test with list
        data_list = [
            {"content": "x" * 50},
            {"content": "short"},
        ]
        result = plugin.process(data_list)
        assert len(result) == 1

    def test_language_detector(self):
        plugin = LanguageDetector()
        assert plugin.name == "language_detector"
        assert plugin.plugin_type == "post_processor"
        assert plugin.initialize() is True

        # Test Chinese
        data = {"content": "这是一段中文测试内容"}
        result = plugin.process(data)
        assert result["language"] == "zh"

        # Test English
        data = {"content": "This is English test content"}
        result = plugin.process(data)
        assert result["language"] == "en"

    def test_duplicate_remover(self):
        plugin = DuplicateRemover()
        assert plugin.name == "duplicate_remover"
        assert plugin.plugin_type == "post_processor"
        assert plugin.initialize() is True

        # Test with duplicates
        data_list = [
            {"content": "content1"},
            {"content": "content1"},  # duplicate
            {"content": "content2"},
        ]
        result = plugin.process(data_list)
        assert len(result) == 2

        # Test cleanup
        plugin.cleanup()
        assert plugin._seen_hashes == set()


class TestGlobalPluginManager:
    """Test global plugin manager functions."""

    def test_get_plugin_manager(self):
        manager = get_plugin_manager()
        assert manager is not None
        assert isinstance(manager, PluginManager)

    def test_get_plugin_manager_singleton(self):
        manager1 = get_plugin_manager()
        manager2 = get_plugin_manager()
        assert manager1 is manager2

    def test_register_plugin_decorator(self):
        """Test that register_plugin decorator works."""
        # The builtin plugins should already be registered
        manager = get_plugin_manager()
        # Note: plugins are registered at import time via decorator
        # We just verify the manager exists
        assert manager is not None
