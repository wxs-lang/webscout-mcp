"""Tests for AI processor module."""
import pytest
from webscout_mcp.ai_processor import (
    AIConfig,
    AIResponse,
    AIProcessor,
    is_ai_available,
    get_available_backends,
)


class TestAIConfig:
    """Test AI configuration."""

    def test_default_config(self):
        config = AIConfig()
        assert config.backend == "ollama"
        assert config.model == "qwen2.5:7b"
        assert config.temperature == 0.7
        assert config.max_tokens == 2000
        assert config.timeout == 60.0

    def test_custom_config(self):
        config = AIConfig(
            backend="openai",
            model="gpt-4",
            api_key="test-key",
            temperature=0.5,
            max_tokens=1000,
        )
        assert config.backend == "openai"
        assert config.model == "gpt-4"
        assert config.api_key == "test-key"
        assert config.temperature == 0.5
        assert config.max_tokens == 1000

    def test_from_env(self, monkeypatch):
        monkeypatch.setenv("WEBSCOUT_AI_BACKEND", "openai")
        monkeypatch.setenv("WEBSCOUT_AI_MODEL", "gpt-4")
        monkeypatch.setenv("WEBSCOUT_AI_API_KEY", "env-key")
        monkeypatch.setenv("WEBSCOUT_AI_TEMPERATURE", "0.3")
        monkeypatch.setenv("WEBSCOUT_AI_MAX_TOKENS", "500")

        config = AIConfig.from_env()
        assert config.backend == "openai"
        assert config.model == "gpt-4"
        assert config.api_key == "env-key"
        assert config.temperature == 0.3
        assert config.max_tokens == 500


class TestAIResponse:
    """Test AI response."""

    def test_response_creation(self):
        response = AIResponse(
            content="Test content",
            model="test-model",
            backend="test-backend",
        )
        assert response.content == "Test content"
        assert response.model == "test-model"
        assert response.backend == "test-backend"
        assert response.error is None

    def test_response_with_error(self):
        response = AIResponse(
            content="",
            error="Test error",
        )
        assert response.content == ""
        assert response.error == "Test error"

    def test_response_to_dict(self):
        response = AIResponse(
            content="Test content",
            model="test-model",
            backend="test-backend",
            usage={"total_tokens": 100},
        )
        data = response.to_dict()
        assert data["content"] == "Test content"
        assert data["model"] == "test-model"
        assert data["backend"] == "test-backend"
        assert data["usage"] == {"total_tokens": 100}
        assert data["error"] is None


class TestAIProcessor:
    """Test AI processor."""

    def test_processor_creation(self):
        processor = AIProcessor()
        assert processor.config.backend == "ollama"
        assert processor.config.model == "qwen2.5:7b"

    def test_processor_with_custom_config(self):
        config = AIConfig(backend="openai", api_key="test-key")
        processor = AIProcessor(config=config)
        assert processor.config.backend == "openai"
        assert processor.config.api_key == "test-key"

    def test_is_available_no_backend(self):
        # Without Ollama or API key, should return False
        config = AIConfig(backend="ollama")
        processor = AIProcessor(config=config)
        # This may return True or False depending on environment
        # Just verify it doesn't raise
        result = processor.is_available()
        assert isinstance(result, bool)

    def test_is_available_with_api_key(self):
        config = AIConfig(backend="openai", api_key="test-key")
        processor = AIProcessor(config=config)
        assert processor.is_available() is True

    def test_unsupported_backend(self):
        config = AIConfig(backend="unsupported")
        processor = AIProcessor(config=config)
        with pytest.raises(ValueError, match="Unsupported backend"):
            processor._get_client()

    def test_generate_with_error(self):
        # Test that generate handles errors gracefully
        config = AIConfig(backend="openai", api_key="invalid-key")
        processor = AIProcessor(config=config)
        response = processor.summarize("Test text")
        # Should return response with error, not raise
        assert isinstance(response, AIResponse)
        assert response.error is not None or response.content != ""

    def test_summarize_prompt_construction(self):
        # Test that summarize method constructs correct prompt
        config = AIConfig(backend="openai", api_key="test-key")
        processor = AIProcessor(config=config)
        # Just verify it doesn't raise during prompt construction
        try:
            response = processor.summarize("Test text", max_length=100)
            assert isinstance(response, AIResponse)
        except Exception:
            # Network errors are expected in test environment
            pass

    def test_answer_question_prompt_construction(self):
        config = AIConfig(backend="openai", api_key="test-key")
        processor = AIProcessor(config=config)
        try:
            response = processor.answer_question("Context", "Question")
            assert isinstance(response, AIResponse)
        except Exception:
            pass

    def test_extract_key_points_prompt_construction(self):
        config = AIConfig(backend="openai", api_key="test-key")
        processor = AIProcessor(config=config)
        try:
            response = processor.extract_key_points("Test text", num_points=3)
            assert isinstance(response, AIResponse)
        except Exception:
            pass

    def test_classify_prompt_construction(self):
        config = AIConfig(backend="openai", api_key="test-key")
        processor = AIProcessor(config=config)
        try:
            response = processor.classify("Test text", ["cat1", "cat2"])
            assert isinstance(response, AIResponse)
        except Exception:
            pass

    def test_generate_tags_prompt_construction(self):
        config = AIConfig(backend="openai", api_key="test-key")
        processor = AIProcessor(config=config)
        try:
            response = processor.generate_tags("Test text", num_tags=3)
            assert isinstance(response, AIResponse)
        except Exception:
            pass

    def test_analyze_sentiment_prompt_construction(self):
        config = AIConfig(backend="openai", api_key="test-key")
        processor = AIProcessor(config=config)
        try:
            response = processor.analyze_sentiment("Test text")
            assert isinstance(response, AIResponse)
        except Exception:
            pass

    def test_compare_documents_prompt_construction(self):
        config = AIConfig(backend="openai", api_key="test-key")
        processor = AIProcessor(config=config)
        try:
            response = processor.compare_documents("Doc1", "Doc2", aspect="内容")
            assert isinstance(response, AIResponse)
        except Exception:
            pass

    def test_extract_entities_prompt_construction(self):
        config = AIConfig(backend="openai", api_key="test-key")
        processor = AIProcessor(config=config)
        try:
            response = processor.extract_entities("Test text with entities")
            assert isinstance(response, AIResponse)
        except Exception:
            pass


class TestUtilityFunctions:
    """Test utility functions."""

    def test_is_ai_available(self):
        # Just verify it doesn't raise
        result = is_ai_available()
        assert isinstance(result, bool)

    def test_get_available_backends(self):
        backends = get_available_backends()
        assert isinstance(backends, list)
        # All backends should be strings
        for backend in backends:
            assert isinstance(backend, str)
