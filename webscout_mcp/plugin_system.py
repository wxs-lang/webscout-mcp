"""Plugin system for webscout-mcp.
Provides a flexible plugin architecture for extending functionality.

Features:
- Plugin discovery and loading
- Standardized plugin interfaces
- Plugin lifecycle management
- Plugin configuration
- Hot plugin loading/unloading
- Plugin dependency management
- Built-in plugin registry
"""
from __future__ import annotations
import os
import sys
import importlib
import importlib.util
from dataclasses import dataclass, field
from typing import Optional, Any, Callable, Type
from abc import ABC, abstractmethod
from .logging import get_logger

log = get_logger(__name__)


class Plugin(ABC):
    """Base class for all plugins.

    All plugins must inherit from this class and implement the required methods.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Plugin name (unique identifier)."""
        pass

    @property
    def version(self) -> str:
        """Plugin version."""
        return "0.1.0"

    @property
    def description(self) -> str:
        """Plugin description."""
        return ""

    @property
    def author(self) -> str:
        """Plugin author."""
        return ""

    @property
    def dependencies(self) -> list[str]:
        """List of required plugin names."""
        return []

    @property
    def plugin_type(self) -> str:
        """Plugin type (e.g., 'search_backend', 'extractor', 'alert_channel')."""
        return "generic"

    def initialize(self, config: Optional[dict] = None) -> bool:
        """Initialize the plugin.

        Args:
            config: Plugin configuration dictionary.

        Returns:
            True if initialization succeeded, False otherwise.
        """
        return True

    def cleanup(self) -> None:
        """Cleanup plugin resources."""
        pass

    def get_info(self) -> dict:
        """Get plugin information."""
        return {
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "author": self.author,
            "dependencies": self.dependencies,
            "plugin_type": self.plugin_type,
        }


class SearchBackendPlugin(Plugin):
    """Base class for search backend plugins."""

    @property
    def plugin_type(self) -> str:
        return "search_backend"

    @abstractmethod
    def search(self, query: str, max_results: int = 10, **kwargs) -> list[dict]:
        """Search for query.

        Args:
            query: Search query.
            max_results: Maximum number of results.
            **kwargs: Additional search parameters.

        Returns:
            List of search results (dicts with title, url, snippet).
        """
        pass


class ExtractorPlugin(Plugin):
    """Base class for content extractor plugins."""

    @property
    def plugin_type(self) -> str:
        return "extractor"

    @abstractmethod
    def extract(self, html: str, url: str = "", **kwargs) -> dict:
        """Extract content from HTML.

        Args:
            html: HTML content.
            url: Source URL.
            **kwargs: Additional extraction parameters.

        Returns:
            Dictionary with extracted content (title, content, metadata).
        """
        pass


class AlertChannelPlugin(Plugin):
    """Base class for alert channel plugins."""

    @property
    def plugin_type(self) -> str:
        return "alert_channel"

    @abstractmethod
    def send_alert(self, title: str, content: str, **kwargs) -> bool:
        """Send an alert.

        Args:
            title: Alert title.
            content: Alert content.
            **kwargs: Additional alert parameters.

        Returns:
            True if alert was sent successfully.
        """
        pass


class PostProcessorPlugin(Plugin):
    """Base class for post-processor plugins."""

    @property
    def plugin_type(self) -> str:
        return "post_processor"

    @abstractmethod
    def process(self, data: Any, **kwargs) -> Any:
        """Process data after fetching/extraction.

        Args:
            data: Input data.
            **kwargs: Additional processing parameters.

        Returns:
            Processed data.
        """
        pass


@dataclass
class PluginInfo:
    """Information about a loaded plugin."""
    name: str
    version: str
    plugin_type: str
    description: str = ""
    author: str = ""
    dependencies: list[str] = field(default_factory=list)
    enabled: bool = True
    loaded: bool = False
    instance: Optional[Plugin] = None
    config: dict = field(default_factory=dict)
    error: str = ""

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "version": self.version,
            "plugin_type": self.plugin_type,
            "description": self.description,
            "author": self.author,
            "dependencies": self.dependencies,
            "enabled": self.enabled,
            "loaded": self.loaded,
            "config": self.config,
            "error": self.error,
        }


class PluginManager:
    """Manages plugin discovery, loading, and lifecycle.

    Features:
    - Discover plugins from directories and entry points
    - Load and unload plugins dynamically
    - Manage plugin dependencies
    - Plugin configuration
    - Plugin type filtering
    - Built-in plugin registry
    """

    def __init__(
        self,
        plugin_dirs: Optional[list[str]] = None,
        auto_discover: bool = True,
    ) -> None:
        self._plugins: dict[str, PluginInfo] = {}
        self._plugin_dirs: list[str] = plugin_dirs or []
        self._builtin_plugins: dict[str, Type[Plugin]] = {}

        if auto_discover:
            self.discover()

    def add_plugin_dir(self, directory: str) -> None:
        """Add a directory for plugin discovery.

        Args:
            directory: Path to plugin directory.
        """
        if os.path.isdir(directory) and directory not in self._plugin_dirs:
            self._plugin_dirs.append(directory)
            log.info("Plugin directory added", extra={"directory": directory})

    def register_builtin(self, plugin_class: Type[Plugin]) -> None:
        """Register a built-in plugin class.

        Args:
            plugin_class: Plugin class to register.
        """
        # Create a temporary instance to get name
        try:
            temp_instance = plugin_class()
            name = temp_instance.name
            self._builtin_plugins[name] = plugin_class
            log.info("Built-in plugin registered", extra={"plugin_name": name, "type": temp_instance.plugin_type})
        except Exception as exc:
            log.error("Failed to register built-in plugin", extra={"error": str(exc)})

    def discover(self) -> list[str]:
        """Discover plugins from configured directories and entry points.

        Returns:
            List of discovered plugin names.
        """
        discovered = []

        # Discover from directories
        for directory in self._plugin_dirs:
            if not os.path.isdir(directory):
                continue
            for filename in os.listdir(directory):
                if filename.endswith(".py") and not filename.startswith("_"):
                    plugin_path = os.path.join(directory, filename)
                    try:
                        name = self._load_plugin_from_file(plugin_path)
                        if name:
                            discovered.append(name)
                    except Exception as exc:
                        log.warning("Failed to load plugin file", extra={"file": filename, "error": str(exc)})

        # Discover from entry points
        try:
            if sys.version_info >= (3, 10):
                from importlib.metadata import entry_points
                eps = entry_points(group="webscout_mcp.plugins")
                for ep in eps:
                    try:
                        plugin_class = ep.load()
                        self.register_builtin(plugin_class)
                        discovered.append(ep.name)
                    except Exception as exc:
                        log.warning("Failed to load entry point plugin", extra={"plugin_name": ep.name, "error": str(exc)})
        except Exception:
            pass  # Entry points not available

        log.info("Plugin discovery completed", extra={"discovered": len(discovered)})
        return discovered

    def _load_plugin_from_file(self, filepath: str) -> Optional[str]:
        """Load a plugin from a Python file.

        Args:
            filepath: Path to plugin file.

        Returns:
            Plugin name if loaded successfully, None otherwise.
        """
        module_name = os.path.splitext(os.path.basename(filepath))[0]
        spec = importlib.util.spec_from_file_location(module_name, filepath)
        if not spec or not spec.loader:
            return None

        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)

        # Find Plugin subclasses in module
        for attr_name in dir(module):
            attr = getattr(module, attr_name)
            if (
                isinstance(attr, type)
                and issubclass(attr, Plugin)
                and attr is not Plugin
                and attr is not SearchBackendPlugin
                and attr is not ExtractorPlugin
                and attr is not AlertChannelPlugin
                and attr is not PostProcessorPlugin
            ):
                self.register_builtin(attr)
                temp_instance = attr()
                return temp_instance.name

        return None

    def load_plugin(self, name: str, config: Optional[dict] = None) -> bool:
        """Load and initialize a plugin.

        Args:
            name: Plugin name.
            config: Plugin configuration.

        Returns:
            True if plugin loaded successfully.
        """
        if name not in self._builtin_plugins:
            log.error("Plugin not found", extra={"plugin_name": name})
            return False

        plugin_class = self._builtin_plugins[name]

        try:
            # Check dependencies
            temp_instance = plugin_class()
            for dep in temp_instance.dependencies:
                if dep not in self._plugins or not self._plugins[dep].loaded:
                    log.error("Plugin dependency not loaded", extra={"plugin": name, "dependency": dep})
                    return False

            # Create and initialize instance
            instance = plugin_class()
            success = instance.initialize(config or {})

            if not success:
                log.error("Plugin initialization failed", extra={"plugin_name": name})
                return False

            # Store plugin info
            info = PluginInfo(
                name=instance.name,
                version=instance.version,
                plugin_type=instance.plugin_type,
                description=instance.description,
                author=instance.author,
                dependencies=instance.dependencies,
                enabled=True,
                loaded=True,
                instance=instance,
                config=config or {},
            )
            self._plugins[name] = info

            log.info("Plugin loaded successfully", extra={"plugin_name": name, "type": instance.plugin_type})
            return True

        except Exception as exc:
            log.error("Failed to load plugin", extra={"plugin_name": name, "error": str(exc)})
            if name in self._plugins:
                self._plugins[name].error = str(exc)
                self._plugins[name].loaded = False
            return False

    def unload_plugin(self, name: str) -> bool:
        """Unload a plugin.

        Args:
            name: Plugin name.

        Returns:
            True if plugin unloaded successfully.
        """
        if name not in self._plugins:
            return False

        try:
            info = self._plugins[name]
            if info.instance:
                info.instance.cleanup()
            info.loaded = False
            info.instance = None
            log.info("Plugin unloaded", extra={"plugin_name": name})
            return True
        except Exception as exc:
            log.error("Failed to unload plugin", extra={"plugin_name": name, "error": str(exc)})
            return False

    def get_plugin(self, name: str) -> Optional[Plugin]:
        """Get a loaded plugin instance.

        Args:
            name: Plugin name.

        Returns:
            Plugin instance if loaded, None otherwise.
        """
        if name in self._plugins and self._plugins[name].loaded:
            return self._plugins[name].instance
        return None

    def get_plugins_by_type(self, plugin_type: str) -> list[Plugin]:
        """Get all loaded plugins of a specific type.

        Args:
            plugin_type: Plugin type filter.

        Returns:
            List of plugin instances.
        """
        return [
            info.instance
            for info in self._plugins.values()
            if info.loaded and info.plugin_type == plugin_type and info.instance
        ]

    def get_all_plugins(self) -> list[PluginInfo]:
        """Get information about all registered plugins.

        Returns:
            List of plugin information objects.
        """
        # Include registered but not loaded plugins
        all_names = set(self._plugins.keys()) | set(self._builtin_plugins.keys())
        result = []
        for name in all_names:
            if name in self._plugins:
                result.append(self._plugins[name])
            else:
                # Create info for registered but not loaded plugin
                try:
                    plugin_class = self._builtin_plugins[name]
                    temp_instance = plugin_class()
                    result.append(PluginInfo(
                        name=temp_instance.name,
                        version=temp_instance.version,
                        plugin_type=temp_instance.plugin_type,
                        description=temp_instance.description,
                        author=temp_instance.author,
                        dependencies=temp_instance.dependencies,
                        loaded=False,
                    ))
                except Exception:
                    pass
        return result

    def enable_plugin(self, name: str) -> bool:
        """Enable a plugin.

        Args:
            name: Plugin name.

        Returns:
            True if plugin enabled.
        """
        if name in self._plugins:
            self._plugins[name].enabled = True
            return True
        return False

    def disable_plugin(self, name: str) -> bool:
        """Disable a plugin.

        Args:
            name: Plugin name.

        Returns:
            True if plugin disabled.
        """
        if name in self._plugins:
            self._plugins[name].enabled = False
            if self._plugins[name].loaded:
                self.unload_plugin(name)
            return True
        return False

    def reload_plugin(self, name: str, config: Optional[dict] = None) -> bool:
        """Reload a plugin.

        Args:
            name: Plugin name.
            config: New plugin configuration.

        Returns:
            True if plugin reloaded successfully.
        """
        self.unload_plugin(name)
        return self.load_plugin(name, config)

    def get_stats(self) -> dict:
        """Get plugin manager statistics."""
        loaded = sum(1 for p in self._plugins.values() if p.loaded)
        enabled = sum(1 for p in self._plugins.values() if p.enabled)
        by_type = {}
        for info in self._plugins.values():
            if info.loaded:
                by_type[info.plugin_type] = by_type.get(info.plugin_type, 0) + 1

        return {
            "total_registered": len(self._builtin_plugins),
            "total_loaded": loaded,
            "total_enabled": enabled,
            "by_type": by_type,
            "plugin_dirs": self._plugin_dirs,
        }


# Global plugin manager instance
_plugin_manager: Optional[PluginManager] = None


def get_plugin_manager() -> PluginManager:
    """Get the global plugin manager instance."""
    global _plugin_manager
    if _plugin_manager is None:
        _plugin_manager = PluginManager()
    return _plugin_manager


def register_plugin(plugin_class: Type[Plugin]) -> Type[Plugin]:
    """Decorator to register a plugin class.

    Usage:
        @register_plugin
        class MyPlugin(Plugin):
            ...
    """
    manager = get_plugin_manager()
    manager.register_builtin(plugin_class)
    return plugin_class
