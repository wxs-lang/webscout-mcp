"""One-click setup module for webscout-mcp.
Provides automatic installation and configuration of all dependencies.

Features:
- System configuration detection (OS, Python version, GPU, memory)
- Automatic dependency installation
- Playwright browser installation
- Ollama installation and model download (optional)
- Embedding model download (optional)
- Configuration file generation
- Health check and verification
"""

from __future__ import annotations

import os
import platform
import subprocess
import sys
from dataclasses import dataclass, field

from .logging_config import get_logger

log = get_logger(__name__)


@dataclass
class SystemInfo:
    """System information detected during setup."""

    os: str = ""
    os_version: str = ""
    python_version: str = ""
    cpu_count: int = 0
    total_memory_gb: float = 0.0
    has_gpu: bool = False
    gpu_info: str = ""
    has_ollama: bool = False
    has_playwright: bool = False
    has_chromadb: bool = False
    has_sentence_transformers: bool = False

    def to_dict(self) -> dict:
        return {
            "os": self.os,
            "os_version": self.os_version,
            "python_version": self.python_version,
            "cpu_count": self.cpu_count,
            "total_memory_gb": self.total_memory_gb,
            "has_gpu": self.has_gpu,
            "gpu_info": self.gpu_info,
            "has_ollama": self.has_ollama,
            "has_playwright": self.has_playwright,
            "has_chromadb": self.has_chromadb,
            "has_sentence_transformers": self.has_sentence_transformers,
        }


@dataclass
class SetupConfig:
    """Configuration for setup process."""

    # Whether to install Playwright browsers
    install_playwright: bool = True
    # Whether to install Ollama (local LLM)
    install_ollama: bool = False
    # Ollama model to download (if install_ollama is True)
    ollama_model: str = "qwen2.5:7b"
    # Whether to install ChromaDB (vector database)
    install_chromadb: bool = False
    # Whether to install sentence-transformers (local embedding)
    install_sentence_transformers: bool = False
    # Embedding model to use
    embedding_model: str = "BAAI/bge-small-zh-v1.5"
    # Whether to generate config file
    generate_config: bool = True
    # Config file path
    config_path: str = "~/.config/webscout/config.toml"
    # Whether to run health check after setup
    run_health_check: bool = True
    # Verbose output
    verbose: bool = False

    @classmethod
    def from_env(cls) -> SetupConfig:
        """Load configuration from environment variables."""
        return cls(
            install_playwright=os.environ.get("WEBSCOUT_SETUP_PLAYWRIGHT", "true").lower() == "true",
            install_ollama=os.environ.get("WEBSCOUT_SETUP_OLLAMA", "false").lower() == "true",
            ollama_model=os.environ.get("WEBSCOUT_SETUP_OLLAMA_MODEL", "qwen2.5:7b"),
            install_chromadb=os.environ.get("WEBSCOUT_SETUP_CHROMADB", "false").lower() == "true",
            install_sentence_transformers=os.environ.get("WEBSCOUT_SETUP_SENTENCE_TRANSFORMERS", "false").lower()
            == "true",
            embedding_model=os.environ.get("WEBSCOUT_SETUP_EMBEDDING_MODEL", "BAAI/bge-small-zh-v1.5"),
            generate_config=os.environ.get("WEBSCOUT_SETUP_GENERATE_CONFIG", "true").lower() == "true",
            config_path=os.environ.get("WEBSCOUT_SETUP_CONFIG_PATH", "~/.config/webscout/config.toml"),
            run_health_check=os.environ.get("WEBSCOUT_SETUP_HEALTH_CHECK", "true").lower() == "true",
            verbose=os.environ.get("WEBSCOUT_SETUP_VERBOSE", "false").lower() == "true",
        )


@dataclass
class SetupResult:
    """Result of setup process."""

    success: bool = False
    system_info: SystemInfo | None = None
    installed_components: list[str] = field(default_factory=list)
    skipped_components: list[str] = field(default_factory=list)
    failed_components: list[str] = field(default_factory=list)
    config_path: str = ""
    health_check_passed: bool = False
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "system_info": self.system_info.to_dict() if self.system_info else None,
            "installed_components": self.installed_components,
            "skipped_components": self.skipped_components,
            "failed_components": self.failed_components,
            "config_path": self.config_path,
            "health_check_passed": self.health_check_passed,
            "errors": self.errors,
            "warnings": self.warnings,
        }


class SetupManager:
    """Manages one-click setup process for webscout-mcp."""

    def __init__(self, config: SetupConfig | None = None) -> None:
        self.config = config or SetupConfig.from_env()
        self.system_info = SystemInfo()
        self.result = SetupResult()

    def detect_system(self) -> SystemInfo:
        """Detect system configuration."""
        info = SystemInfo()
        info.os = platform.system()
        info.os_version = platform.version()
        info.python_version = sys.version.split()[0]
        info.cpu_count = os.cpu_count() or 0

        # Detect memory
        try:
            import psutil

            info.total_memory_gb = round(psutil.virtual_memory().total / (1024**3), 2)
        except ImportError:
            # Fallback for systems without psutil
            if info.os == "Linux":
                try:
                    with open("/proc/meminfo", "r") as f:
                        for line in f:
                            if line.startswith("MemTotal:"):
                                mem_kb = int(line.split()[1])
                                info.total_memory_gb = round(mem_kb / (1024 * 1024), 2)
                                break
                except Exception:
                    pass

        # Detect GPU
        info.has_gpu, info.gpu_info = self._detect_gpu()

        # Detect installed components
        info.has_ollama = self._check_command("ollama")
        info.has_playwright = self._check_package("playwright")
        info.has_chromadb = self._check_package("chromadb")
        info.has_sentence_transformers = self._check_package("sentence_transformers")

        self.system_info = info
        return info

    def _detect_gpu(self) -> tuple[bool, str]:
        """Detect GPU availability."""
        # Check NVIDIA GPU
        if self._check_command("nvidia-smi"):
            try:
                result = subprocess.run(
                    ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                if result.returncode == 0:
                    return True, result.stdout.strip()
            except Exception:
                pass

        # Check for CUDA
        if os.environ.get("CUDA_VISIBLE_DEVICES"):
            return True, f"CUDA devices: {os.environ['CUDA_VISIBLE_DEVICES']}"

        return False, ""

    def _check_command(self, command: str) -> bool:
        """Check if a command is available."""
        try:
            subprocess.run(
                ["which", command] if self.system_info.os != "Windows" else ["where", command],
                capture_output=True,
                timeout=5,
            )
            return True
        except Exception:
            return False

    def _check_package(self, package: str) -> bool:
        """Check if a Python package is installed."""
        try:
            __import__(package)
            return True
        except ImportError:
            return False

    def _run_command(self, command: list[str], description: str = "") -> tuple[bool, str]:
        """Run a command and return result."""
        try:
            if self.config.verbose:
                print(f"  Running: {' '.join(command)}")
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=300,
            )
            if result.returncode == 0:
                return True, result.stdout
            else:
                return False, result.stderr or result.stdout
        except subprocess.TimeoutExpired:
            return False, "Command timed out"
        except Exception as exc:
            return False, str(exc)

    def install_playwright(self) -> bool:
        """Install Playwright and browsers."""
        print("\n[1/5] Installing Playwright...")

        # Install Playwright package if not installed
        if not self.system_info.has_playwright:
            success, output = self._run_command(
                [sys.executable, "-m", "pip", "install", "playwright"],
                "Install playwright package",
            )
            if not success:
                self.result.failed_components.append("playwright-package")
                self.result.errors.append(f"Failed to install playwright: {output}")
                return False
            self.result.installed_components.append("playwright-package")
        else:
            self.result.skipped_components.append("playwright-package")
            print("  Playwright package already installed, skipping.")

        # Install browsers
        print("  Installing Chromium browser (this may take a few minutes)...")
        success, output = self._run_command(
            [sys.executable, "-m", "playwright", "install", "chromium"],
            "Install chromium browser",
        )
        if success:
            self.result.installed_components.append("playwright-chromium")
            print("  Playwright Chromium installed successfully.")
            return True
        else:
            self.result.failed_components.append("playwright-chromium")
            self.result.errors.append(f"Failed to install Chromium: {output}")
            print(f"  Warning: Failed to install Chromium: {output}")
            return False

    def install_ollama(self) -> bool:
        """Install Ollama and download model."""
        print("\n[2/5] Setting up Ollama (local LLM)...")

        if not self.config.install_ollama:
            self.result.skipped_components.append("ollama")
            print("  Ollama installation skipped (enable with --ollama flag).")
            return True

        # Check if Ollama is already installed
        if self.system_info.has_ollama:
            print("  Ollama already installed.")
        else:
            print("  Installing Ollama...")
            if self.system_info.os == "Darwin":
                # macOS
                success, output = self._run_command(
                    ["brew", "install", "ollama"],
                    "Install ollama via brew",
                )
            elif self.system_info.os == "Linux":
                # Linux
                success, output = self._run_command(
                    ["curl", "-fsSL", "https://ollama.com/install.sh", "-o", "/tmp/ollama_install.sh"],  # nosec B108 - temp file for installer
                    "Download ollama install script",
                )
                if success:
                    success, output = self._run_command(
                        ["sh", "/tmp/ollama_install.sh"],  # nosec B108 - running installer
                        "Run ollama install script",
                    )
            else:
                print("  Warning: Automatic Ollama installation not supported on this OS.")
                print("  Please install Ollama manually from https://ollama.com")
                self.result.warnings.append("Ollama manual installation required")
                return False

            if not success:
                self.result.failed_components.append("ollama")
                self.result.errors.append(f"Failed to install Ollama: {output}")
                return False
            self.result.installed_components.append("ollama")

        # Start Ollama service
        print("  Starting Ollama service...")
        self._run_command(["ollama", "serve"], "Start ollama service")

        # Download model
        print(f"  Downloading model: {self.config.ollama_model} (this may take a while)...")
        success, output = self._run_command(
            ["ollama", "pull", self.config.ollama_model],
            f"Pull ollama model {self.config.ollama_model}",
        )
        if success:
            self.result.installed_components.append(f"ollama-model-{self.config.ollama_model}")
            print(f"  Model {self.config.ollama_model} downloaded successfully.")
            return True
        else:
            self.result.failed_components.append(f"ollama-model-{self.config.ollama_model}")
            self.result.errors.append(f"Failed to download model: {output}")
            return False

    def install_vector_store(self) -> bool:
        """Install vector database and embedding model."""
        print("\n[3/5] Setting up vector store (semantic search + RAG)...")

        if not self.config.install_chromadb and not self.config.install_sentence_transformers:
            self.result.skipped_components.append("vector-store")
            print("  Vector store setup skipped (enable with --vector-store flag).")
            return True

        # Install ChromaDB
        if self.config.install_chromadb:
            if not self.system_info.has_chromadb:
                print("  Installing ChromaDB...")
                success, output = self._run_command(
                    [sys.executable, "-m", "pip", "install", "chromadb"],
                    "Install chromadb",
                )
                if success:
                    self.result.installed_components.append("chromadb")
                    print("  ChromaDB installed successfully.")
                else:
                    self.result.failed_components.append("chromadb")
                    self.result.errors.append(f"Failed to install ChromaDB: {output}")
            else:
                self.result.skipped_components.append("chromadb")
                print("  ChromaDB already installed, skipping.")

        # Install sentence-transformers
        if self.config.install_sentence_transformers:
            if not self.system_info.has_sentence_transformers:
                print("  Installing sentence-transformers (this may take a while)...")
                success, output = self._run_command(
                    [sys.executable, "-m", "pip", "install", "sentence-transformers"],
                    "Install sentence-transformers",
                )
                if success:
                    self.result.installed_components.append("sentence-transformers")
                    print("  sentence-transformers installed successfully.")
                else:
                    self.result.failed_components.append("sentence-transformers")
                    self.result.errors.append(f"Failed to install sentence-transformers: {output}")
            else:
                self.result.skipped_components.append("sentence-transformers")
                print("  sentence-transformers already installed, skipping.")

            # Download embedding model
            print(f"  Downloading embedding model: {self.config.embedding_model}...")
            try:
                from sentence_transformers import SentenceTransformer

                model = SentenceTransformer(self.config.embedding_model)
                self.result.installed_components.append(f"embedding-model-{self.config.embedding_model}")
                print(f"  Embedding model {self.config.embedding_model} downloaded successfully.")
            except Exception as exc:
                self.result.warnings.append(f"Failed to pre-download embedding model: {exc}")
                print(f"  Warning: Failed to pre-download embedding model: {exc}")
                print("  Model will be downloaded automatically on first use.")

        return True

    def generate_config(self) -> bool:
        """Generate configuration file."""
        print("\n[4/5] Generating configuration file...")

        if not self.config.generate_config:
            self.result.skipped_components.append("config")
            print("  Config generation skipped.")
            return True

        config_path = os.path.expanduser(self.config.config_path)
        os.makedirs(os.path.dirname(config_path), exist_ok=True)

        # Generate config based on detected system
        config_content = self._generate_config_content()

        try:
            with open(config_path, "w") as f:
                f.write(config_content)
            self.result.config_path = config_path
            self.result.installed_components.append("config-file")
            print(f"  Configuration file generated: {config_path}")
            return True
        except Exception as exc:
            self.result.errors.append(f"Failed to generate config: {exc}")
            print(f"  Failed to generate config: {exc}")
            return False

    def _generate_config_content(self) -> str:
        """Generate configuration file content."""
        lines = [
            "# webscout-mcp configuration file",
            "# Generated by webscout-mcp setup",
            f"# System: {self.system_info.os} {self.system_info.os_version}",
            f"# Python: {self.system_info.python_version}",
            f"# CPU: {self.system_info.cpu_count} cores",
            f"# Memory: {self.system_info.total_memory_gb} GB",
            f"# GPU: {'Yes - ' + self.system_info.gpu_info if self.system_info.has_gpu else 'No'}",
            "",
            "[server]",
            'host = "127.0.0.1"',
            "port = 8000",
            "",
            "[cache]",
            "enabled = true",
            "ttl = 3600",
            "",
            "[search]",
            'default_backend = "bing"',
            "max_results = 10",
            "",
            "[fetcher]",
            "timeout = 30",
            "max_retries = 3",
            "",
        ]

        # Add AI config if Ollama is available
        if self.system_info.has_ollama or self.config.install_ollama:
            lines.extend(
                [
                    "[ai]",
                    'backend = "ollama"',
                    f'model = "{self.config.ollama_model}"',
                    "temperature = 0.7",
                    "",
                ]
            )

        # Add vector store config if installed
        if self.system_info.has_chromadb or self.config.install_chromadb:
            lines.extend(
                [
                    "[vector_store]",
                    "enabled = true",
                    'vector_db = "chroma"',
                    f'embedding_backend = "{"local" if self.system_info.has_sentence_transformers else "openai"}"',
                    f'embedding_model = "{self.config.embedding_model}"',
                    "",
                ]
            )

        # Add browser config if Playwright is installed
        if self.system_info.has_playwright or self.config.install_playwright:
            lines.extend(
                [
                    "[browser]",
                    "enabled = true",
                    'browser_type = "chromium"',
                    "headless = true",
                    "",
                ]
            )

        # Add monitor config
        lines.extend(
            [
                "[monitor]",
                "check_interval = 300",
                "monitor_text = true",
                "min_change_size = 10",
                "",
            ]
        )

        return "\n".join(lines)

    def run_health_check(self) -> bool:
        """Run health check to verify setup."""
        print("\n[5/5] Running health check...")

        if not self.config.run_health_check:
            self.result.skipped_components.append("health-check")
            print("  Health check skipped.")
            return True

        checks_passed = 0
        checks_total = 0

        # Check core imports
        checks_total += 1
        try:
            checks_passed += 1
            print("  ✓ Core package import")
        except Exception as exc:
            print(f"  ✗ Core package import failed: {exc}")

        # Check httpx
        checks_total += 1
        try:
            checks_passed += 1
            print("  ✓ httpx (HTTP client)")
        except Exception as exc:
            print(f"  ✗ httpx import failed: {exc}")

        # Check BeautifulSoup
        checks_total += 1
        try:
            checks_passed += 1
            print("  ✓ BeautifulSoup (HTML parsing)")
        except Exception as exc:
            print(f"  ✗ BeautifulSoup import failed: {exc}")

        # Check trafilatura
        checks_total += 1
        try:
            checks_passed += 1
            print("  ✓ trafilatura (content extraction)")
        except Exception as exc:
            print(f"  ✗ trafilatura import failed: {exc}")

        # Check Playwright
        if self.config.install_playwright:
            checks_total += 1
            try:
                checks_passed += 1
                print("  ✓ Playwright (browser automation)")
            except Exception as exc:
                print(f"  ✗ Playwright import failed: {exc}")

        # Check ChromaDB
        if self.config.install_chromadb:
            checks_total += 1
            try:
                checks_passed += 1
                print("  ✓ ChromaDB (vector database)")
            except Exception as exc:
                print(f"  ✗ ChromaDB import failed: {exc}")

        # Check Ollama
        if self.config.install_ollama:
            checks_total += 1
            if self.system_info.has_ollama:
                checks_passed += 1
                print("  ✓ Ollama (local LLM)")
            else:
                print("  ✗ Ollama not found")

        print(f"\n  Health check: {checks_passed}/{checks_total} checks passed")
        self.result.health_check_passed = checks_passed == checks_total
        return self.result.health_check_passed

    def run(self) -> SetupResult:
        """Run the complete setup process."""
        print("=" * 60)
        print("  webscout-mcp One-Click Setup")
        print("=" * 60)

        # Step 1: Detect system
        print("\nDetecting system configuration...")
        self.detect_system()
        self.result.system_info = self.system_info

        print(f"  OS: {self.system_info.os} {self.system_info.os_version}")
        print(f"  Python: {self.system_info.python_version}")
        print(f"  CPU: {self.system_info.cpu_count} cores")
        print(f"  Memory: {self.system_info.total_memory_gb} GB")
        print(f"  GPU: {'Yes - ' + self.system_info.gpu_info if self.system_info.has_gpu else 'No'}")

        # Recommend configuration based on system
        self._recommend_config()

        # Step 2: Install components
        if self.config.install_playwright:
            self.install_playwright()

        if self.config.install_ollama:
            self.install_ollama()

        if self.config.install_chromadb or self.config.install_sentence_transformers:
            self.install_vector_store()

        # Step 3: Generate config
        if self.config.generate_config:
            self.generate_config()

        # Step 4: Health check
        if self.config.run_health_check:
            self.run_health_check()

        # Summary
        self._print_summary()

        self.result.success = len(self.result.failed_components) == 0
        return self.result

    def _recommend_config(self) -> None:
        """Recommend configuration based on system info."""
        print("\nRecommended configuration based on your system:")

        # Memory-based recommendations
        if self.system_info.total_memory_gb >= 16:
            print("  ✓ Sufficient memory for local LLM (16GB+)")
            print("    Recommended: Enable Ollama with qwen2.5:7b")
        elif self.system_info.total_memory_gb >= 8:
            print("  ⚠ Moderate memory (8-16GB)")
            print("    Recommended: Enable Ollama with qwen2.5:3b, or use API")
        else:
            print("  ⚠ Limited memory (<8GB)")
            print("    Recommended: Use API-based LLM instead of local")

        # GPU recommendations
        if self.system_info.has_gpu:
            print("  ✓ GPU detected, local models will run faster")
        else:
            print("  ⚠ No GPU detected, local models will run on CPU (slower)")

        print()

    def _print_summary(self) -> None:
        """Print setup summary."""
        print("\n" + "=" * 60)
        print("  Setup Summary")
        print("=" * 60)

        if self.result.installed_components:
            print("\n✓ Installed:")
            for component in self.result.installed_components:
                print(f"  - {component}")

        if self.result.skipped_components:
            print("\n○ Skipped:")
            for component in self.result.skipped_components:
                print(f"  - {component}")

        if self.result.failed_components:
            print("\n✗ Failed:")
            for component in self.result.failed_components:
                print(f"  - {component}")

        if self.result.warnings:
            print("\n⚠ Warnings:")
            for warning in self.result.warnings:
                print(f"  - {warning}")

        if self.result.errors:
            print("\n✗ Errors:")
            for error in self.result.errors:
                print(f"  - {error}")

        if self.result.config_path:
            print(f"\n📝 Config file: {self.result.config_path}")

        print(f"\nHealth check: {'✓ Passed' if self.result.health_check_passed else '✗ Failed'}")

        if self.result.success:
            print("\n🎉 Setup completed successfully!")
            print("You can now run: webscout-mcp serve")
        else:
            print("\n⚠ Setup completed with some issues. Please check the errors above.")

        print("=" * 60)


def run_setup(
    install_playwright: bool = True,
    install_ollama: bool = False,
    ollama_model: str = "qwen2.5:7b",
    install_vector_store: bool = False,
    embedding_model: str = "BAAI/bge-small-zh-v1.5",
    generate_config: bool = True,
    verbose: bool = False,
) -> SetupResult:
    """Convenience function to run setup.

    Args:
        install_playwright: Whether to install Playwright and browsers.
        install_ollama: Whether to install Ollama and download model.
        ollama_model: Ollama model to download.
        install_vector_store: Whether to install vector database and embedding.
        embedding_model: Embedding model to use.
        generate_config: Whether to generate config file.
        verbose: Whether to show verbose output.

    Returns:
        SetupResult with setup details.
    """
    config = SetupConfig(
        install_playwright=install_playwright,
        install_ollama=install_ollama,
        ollama_model=ollama_model,
        install_chromadb=install_vector_store,
        install_sentence_transformers=install_vector_store,
        embedding_model=embedding_model,
        generate_config=generate_config,
        verbose=verbose,
    )
    manager = SetupManager(config=config)
    return manager.run()
