"""Tests for setup module."""

from webscout_mcp.setup import (
    SetupConfig,
    SetupManager,
    SetupResult,
    SystemInfo,
    run_setup,
)


class TestSystemInfo:
    """Test SystemInfo class."""

    def test_system_info_creation(self):
        info = SystemInfo()
        assert info.os == ""
        assert info.python_version == ""
        assert info.cpu_count == 0
        assert info.total_memory_gb == 0.0
        assert info.has_gpu is False
        assert info.has_ollama is False
        assert info.has_playwright is False

    def test_system_info_to_dict(self):
        info = SystemInfo(
            os="Linux",
            python_version="3.12.0",
            cpu_count=8,
            total_memory_gb=16.0,
            has_gpu=True,
            gpu_info="NVIDIA GeForce RTX 3080",
        )
        data = info.to_dict()
        assert data["os"] == "Linux"
        assert data["python_version"] == "3.12.0"
        assert data["cpu_count"] == 8
        assert data["total_memory_gb"] == 16.0
        assert data["has_gpu"] is True
        assert data["gpu_info"] == "NVIDIA GeForce RTX 3080"


class TestSetupConfig:
    """Test SetupConfig class."""

    def test_default_config(self):
        config = SetupConfig()
        assert config.install_playwright is True
        assert config.install_ollama is False
        assert config.ollama_model == "qwen2.5:7b"
        assert config.install_chromadb is False
        assert config.install_sentence_transformers is False
        assert config.embedding_model == "BAAI/bge-small-zh-v1.5"
        assert config.generate_config is True
        assert config.run_health_check is True
        assert config.verbose is False

    def test_custom_config(self):
        config = SetupConfig(
            install_playwright=False,
            install_ollama=True,
            ollama_model="qwen2.5:3b",
            install_chromadb=True,
            install_sentence_transformers=True,
            verbose=True,
        )
        assert config.install_playwright is False
        assert config.install_ollama is True
        assert config.ollama_model == "qwen2.5:3b"
        assert config.install_chromadb is True
        assert config.install_sentence_transformers is True
        assert config.verbose is True

    def test_from_env(self, monkeypatch):
        monkeypatch.setenv("WEBSCOUT_SETUP_PLAYWRIGHT", "false")
        monkeypatch.setenv("WEBSCOUT_SETUP_OLLAMA", "true")
        monkeypatch.setenv("WEBSCOUT_SETUP_OLLAMA_MODEL", "llama3.1:8b")
        monkeypatch.setenv("WEBSCOUT_SETUP_CHROMADB", "true")
        monkeypatch.setenv("WEBSCOUT_SETUP_SENTENCE_TRANSFORMERS", "true")
        monkeypatch.setenv("WEBSCOUT_SETUP_VERBOSE", "true")

        config = SetupConfig.from_env()
        assert config.install_playwright is False
        assert config.install_ollama is True
        assert config.ollama_model == "llama3.1:8b"
        assert config.install_chromadb is True
        assert config.install_sentence_transformers is True
        assert config.verbose is True


class TestSetupResult:
    """Test SetupResult class."""

    def test_setup_result_creation(self):
        result = SetupResult()
        assert result.success is False
        assert result.installed_components == []
        assert result.skipped_components == []
        assert result.failed_components == []
        assert result.errors == []
        assert result.warnings == []
        assert result.health_check_passed is False

    def test_setup_result_to_dict(self):
        result = SetupResult(
            success=True,
            installed_components=["playwright", "chromadb"],
            skipped_components=["ollama"],
            config_path="/tmp/config.toml",
            health_check_passed=True,
        )
        data = result.to_dict()
        assert data["success"] is True
        assert data["installed_components"] == ["playwright", "chromadb"]
        assert data["skipped_components"] == ["ollama"]
        assert data["config_path"] == "/tmp/config.toml"
        assert data["health_check_passed"] is True


class TestSetupManager:
    """Test SetupManager class."""

    def test_setup_manager_creation(self):
        config = SetupConfig()
        manager = SetupManager(config=config)
        assert manager.config == config
        assert isinstance(manager.system_info, SystemInfo)
        assert isinstance(manager.result, SetupResult)

    def test_setup_manager_with_default_config(self):
        manager = SetupManager()
        assert manager.config.install_playwright is True

    def test_detect_system(self):
        manager = SetupManager()
        info = manager.detect_system()
        assert isinstance(info, SystemInfo)
        assert info.os != ""  # Should detect OS
        assert info.python_version != ""  # Should detect Python version
        assert info.cpu_count > 0  # Should detect CPU count

    def test_detect_gpu(self):
        manager = SetupManager()
        has_gpu, gpu_info = manager._detect_gpu()
        assert isinstance(has_gpu, bool)
        assert isinstance(gpu_info, str)

    def test_check_package_installed(self):
        manager = SetupManager()
        # pytest should be installed in test environment
        assert manager._check_package("pytest") is True

    def test_check_package_not_installed(self):
        manager = SetupManager()
        assert manager._check_package("nonexistent_package_12345") is False

    def test_generate_config_content(self):
        manager = SetupManager()
        manager.detect_system()
        content = manager._generate_config_content()
        assert isinstance(content, str)
        assert "[server]" in content
        assert "[cache]" in content
        assert "[search]" in content
        assert "[fetcher]" in content

    def test_generate_config_content_with_ollama(self):
        config = SetupConfig(install_ollama=True)
        manager = SetupManager(config=config)
        manager.detect_system()
        manager.system_info.has_ollama = True
        content = manager._generate_config_content()
        assert "[ai]" in content
        assert 'backend = "ollama"' in content

    def test_generate_config_content_with_vector_store(self):
        config = SetupConfig(install_chromadb=True, install_sentence_transformers=True)
        manager = SetupManager(config=config)
        manager.detect_system()
        manager.system_info.has_chromadb = True
        manager.system_info.has_sentence_transformers = True
        content = manager._generate_config_content()
        assert "[vector_store]" in content
        assert 'vector_db = "chroma"' in content

    def test_generate_config_content_with_browser(self):
        config = SetupConfig(install_playwright=True)
        manager = SetupManager(config=config)
        manager.detect_system()
        manager.system_info.has_playwright = True
        content = manager._generate_config_content()
        assert "[browser]" in content
        assert 'browser_type = "chromium"' in content


class TestRunSetup:
    """Test run_setup convenience function."""

    def test_run_setup_with_minimal_config(self):
        # Test with all optional components disabled
        result = run_setup(
            install_playwright=False,
            install_ollama=False,
            install_vector_store=False,
            generate_config=False,
        )
        assert isinstance(result, SetupResult)
        # Should complete without errors for core functionality
        assert result.success is True or len(result.failed_components) == 0

    def test_run_setup_returns_result(self):
        result = run_setup(
            install_playwright=False,
            install_ollama=False,
            install_vector_store=False,
            generate_config=False,
        )
        assert isinstance(result, SetupResult)
        assert hasattr(result, "success")
        assert hasattr(result, "installed_components")
        assert hasattr(result, "system_info")
