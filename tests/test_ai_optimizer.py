"""Tests for AI optimizer module."""
import pytest
from webscout_mcp.ai_optimizer import (
    AIResponse,
    PromptTemplate,
    PromptEngineer,
    OutputValidator,
    HallucinationDetector,
    ModelOptimizer,
    AIOptimizer,
    optimize_ai_processing,
)


class TestAIResponse:
    """Test AIResponse class."""

    def test_creation(self):
        resp = AIResponse(content="Test response")
        assert resp.content == "Test response"
        assert resp.is_valid is True
        assert resp.confidence == 0.0

    def test_to_dict(self):
        resp = AIResponse(
            content="Test",
            model="gpt-4",
            total_tokens=100,
            confidence=0.9,
        )
        data = resp.to_dict()
        assert data["content"] == "Test"
        assert data["model"] == "gpt-4"
        assert data["total_tokens"] == 100


class TestPromptTemplate:
    """Test PromptTemplate class."""

    def test_creation(self):
        template = PromptTemplate(
            name="test",
            template="Hello {{name}}",
            variables=["name"],
        )
        assert template.name == "test"
        assert "name" in template.variables

    def test_format(self):
        template = PromptTemplate(
            name="test",
            template="Hello {{name}}, you are {{role}}",
            variables=["name", "role"],
            system_prompt="You are helpful.",
        )
        system, user = template.format(name="Alice", role="admin")
        assert system == "You are helpful."
        assert "Alice" in user
        assert "admin" in user

    def test_format_with_few_shot(self):
        template = PromptTemplate(
            name="test",
            template="Classify: {{text}}",
            variables=["text"],
            few_shot_examples=[
                {"input": "I love it", "output": "positive"},
                {"input": "I hate it", "output": "negative"},
            ],
        )
        _, user = template.format(text="It's okay")
        assert "Example 1" in user
        assert "positive" in user
        assert "negative" in user

    def test_format_json_output(self):
        template = PromptTemplate(
            name="test",
            template="Extract: {{text}}",
            variables=["text"],
            output_format="json",
        )
        _, user = template.format(text="test")
        assert "JSON" in user


class TestPromptEngineer:
    """Test PromptEngineer class."""

    def test_creation(self):
        engineer = PromptEngineer()
        assert engineer is not None

    def test_get_builtin_template(self):
        engineer = PromptEngineer()
        template = engineer.get_template("summarize")
        assert template is not None
        assert template.name == "summarize"

    def test_get_nonexistent_template(self):
        engineer = PromptEngineer()
        assert engineer.get_template("nonexistent") is None

    def test_register_custom_template(self):
        engineer = PromptEngineer()
        template = PromptTemplate(name="custom", template="Test {{var}}", variables=["var"])
        engineer.register_template(template)
        assert engineer.get_template("custom") is not None

    def test_list_templates(self):
        engineer = PromptEngineer()
        templates = engineer.list_templates()
        assert "summarize" in templates
        assert "extract_entities" in templates
        assert "classify" in templates

    def test_create_cot_prompt(self):
        engineer = PromptEngineer()
        system, user = engineer.create_cot_prompt("What is 2+2?")
        assert "step by step" in system.lower() or "step" in system.lower()
        assert "2+2" in user

    def test_create_few_shot_prompt(self):
        engineer = PromptEngineer()
        examples = [
            {"input": "happy", "output": "positive"},
            {"input": "sad", "output": "negative"},
        ]
        system, user = engineer.create_few_shot_prompt("sentiment analysis", examples, "angry")
        assert "sentiment analysis" in system
        assert "Example 1" in user
        assert "angry" in user


class TestOutputValidator:
    """Test OutputValidator class."""

    def test_validate_json_valid(self):
        validator = OutputValidator()
        is_valid, parsed, errors = validator.validate_json('{"key": "value"}')
        assert is_valid is True
        assert parsed["key"] == "value"
        assert len(errors) == 0

    def test_validate_json_invalid(self):
        validator = OutputValidator()
        is_valid, parsed, errors = validator.validate_json("not json")
        assert is_valid is False
        assert parsed is None
        assert len(errors) > 0

    def test_validate_json_in_markdown(self):
        validator = OutputValidator()
        json_text = '```json\n{"key": "value"}\n```'
        is_valid, parsed, errors = validator.validate_json(json_text)
        assert is_valid is True
        assert parsed["key"] == "value"

    def test_validate_classification_valid(self):
        validator = OutputValidator()
        is_valid, category, errors = validator.validate_classification(
            "The category is positive",
            ["positive", "negative", "neutral"],
        )
        assert is_valid is True
        assert category == "positive"

    def test_validate_classification_invalid(self):
        validator = OutputValidator()
        is_valid, category, errors = validator.validate_classification(
            "Something else",
            ["positive", "negative"],
        )
        assert is_valid is False

    def test_validate_sentiment(self):
        validator = OutputValidator()
        is_valid, sentiment, _ = validator.validate_sentiment("This is positive")
        assert is_valid is True
        assert sentiment == "positive"

    def test_validate_length_valid(self):
        validator = OutputValidator()
        is_valid, errors = validator.validate_length("Hello", min_length=1, max_length=100)
        assert is_valid is True

    def test_validate_length_too_short(self):
        validator = OutputValidator()
        is_valid, errors = validator.validate_length("Hi", min_length=10)
        assert is_valid is False
        assert len(errors) > 0


class TestHallucinationDetector:
    """Test HallucinationDetector class."""

    def test_creation(self):
        detector = HallucinationDetector()
        assert detector is not None

    def test_detect_no_hallucination(self):
        detector = HallucinationDetector()
        output = "The sky is blue. Water is wet."
        context = "The sky is blue. Water is wet. Grass is green."
        score, indicators = detector.detect(output, context)
        assert score < 0.5

    def test_detect_uncertainty(self):
        detector = HallucinationDetector()
        output = "I think the answer might be 42, but I'm not sure."
        score, indicators = detector.detect(output)
        assert score > 0
        assert len(indicators) > 0

    def test_detect_unsupported_claims(self):
        detector = HallucinationDetector()
        output = "The company was founded in 1990 by John Smith in New York City with 500 employees."
        context = "The company makes software products."
        score, indicators = detector.detect(output, context)
        assert score > 0

    def test_detect_empty_output(self):
        detector = HallucinationDetector()
        score, indicators = detector.detect("")
        assert score == 0.0


class TestModelOptimizer:
    """Test ModelOptimizer class."""

    def test_creation(self):
        optimizer = ModelOptimizer()
        assert optimizer is not None

    def test_select_model_simple(self):
        optimizer = ModelOptimizer()
        model = optimizer.select_model("summarization", complexity="low")
        assert model in ["efficient", "medium", "high_quality"]

    def test_select_model_complex(self):
        optimizer = ModelOptimizer()
        model = optimizer.select_model("reasoning", complexity="high")
        assert model == "high_quality"

    def test_estimate_tokens_english(self):
        optimizer = ModelOptimizer()
        tokens = optimizer.estimate_tokens("Hello world, this is a test.")
        assert tokens > 0
        assert tokens < 20  # Short text should have few tokens

    def test_estimate_tokens_chinese(self):
        optimizer = ModelOptimizer()
        tokens = optimizer.estimate_tokens("这是一段中文测试文本")
        assert tokens > 0

    def test_estimate_tokens_empty(self):
        optimizer = ModelOptimizer()
        assert optimizer.estimate_tokens("") == 0

    def test_cache_response(self):
        optimizer = ModelOptimizer()
        response = AIResponse(content="test")
        optimizer.cache_response("key1", response)
        cached = optimizer.get_cached_response("key1")
        assert cached is not None
        assert cached.content == "test"

    def test_track_usage(self):
        optimizer = ModelOptimizer()
        optimizer.track_usage("model_a", 100)
        optimizer.track_usage("model_a", 200)
        optimizer.track_usage("model_b", 150)
        stats = optimizer.get_usage_stats()
        assert stats["total_tokens"] == 450
        assert stats["by_model"]["model_a"] == 300


class TestAIOptimizer:
    """Test AIOptimizer class."""

    def test_creation(self):
        optimizer = AIOptimizer()
        assert optimizer.enable_validation is True
        assert optimizer.enable_hallucination_detection is True

    def test_process_with_ai_fn(self):
        optimizer = AIOptimizer()
        def mock_ai(prompt):
            return "This is a summary of the text."
        response = optimizer.process(
            "Python is a programming language. It is popular for data science.",
            task="summarize",
            ai_fn=mock_ai,
        )
        assert response.content == "This is a summary of the text."
        assert response.total_tokens > 0
        assert response.processing_time_ms > 0

    def test_process_fallback(self):
        optimizer = AIOptimizer()
        response = optimizer.process(
            "Python is a programming language. It is popular. It is easy to learn.",
            task="summarize",
        )
        assert len(response.content) > 0
        assert response.confidence == 0.5

    def test_process_json_validation(self):
        optimizer = AIOptimizer()
        def mock_ai(prompt):
            return '{"entities": ["Python", "data science"]}'
        response = optimizer.process(
            "Python is used for data science.",
            task="extract_entities",
            ai_fn=mock_ai,
        )
        assert response.is_valid is True
        assert response.parsed_content is not None

    def test_get_stats(self):
        optimizer = AIOptimizer()
        stats = optimizer.get_stats()
        assert "enable_validation" in stats
        assert "available_templates" in stats
        assert "summarize" in stats["available_templates"]


class TestConvenienceFunction:
    """Test optimize_ai_processing convenience function."""

    def test_optimize_ai_processing(self):
        response = optimize_ai_processing(
            "Python is a programming language. It is popular. It is easy to learn.",
            task="summarize",
        )
        assert isinstance(response, AIResponse)
        assert len(response.content) > 0
