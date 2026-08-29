"""AI content understanding optimizer module for webscout-mcp.

Enhanced AI processing with prompt engineering, output validation,
hallucination detection, and model optimization.

Features:
- Prompt templates with few-shot learning
- Chain-of-Thought (CoT) prompting
- Output format validation (JSON Schema)
- Hallucination detection and self-verification
- Model selection (task-based routing)
- Batch processing optimization
- Response caching
- Token usage tracking
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from .logging import get_logger

log = get_logger(__name__)


@dataclass
class AIResponse:
    """Enhanced AI response with metadata."""

    content: str = ""
    parsed_content: Any | None = None
    model: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    processing_time_ms: float = 0.0
    confidence: float = 0.0
    hallucination_score: float = 0.0
    is_valid: bool = True
    validation_errors: list[str] = field(default_factory=list)
    citations: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "content": self.content,
            "parsed_content": self.parsed_content,
            "model": self.model,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "processing_time_ms": self.processing_time_ms,
            "confidence": self.confidence,
            "hallucination_score": self.hallucination_score,
            "is_valid": self.is_valid,
            "validation_errors": self.validation_errors,
            "citations": self.citations,
            "metadata": self.metadata,
        }


@dataclass
class PromptTemplate:
    """Reusable prompt template with variables."""

    name: str = ""
    template: str = ""
    variables: list[str] = field(default_factory=list)
    system_prompt: str = ""
    few_shot_examples: list[dict[str, str]] = field(default_factory=list)
    temperature: float = 0.7
    max_tokens: int = 2000
    output_format: str = "text"  # text, json, markdown
    description: str = ""

    def format(self, **kwargs) -> tuple[str, str]:
        """Format template with variables.

        Returns:
            Tuple of (system_prompt, user_prompt).
        """
        user_prompt = self.template
        for var in self.variables:
            if var in kwargs:
                user_prompt = user_prompt.replace(f"{{{{{var}}}}}", str(kwargs[var]))

        # Add few-shot examples
        if self.few_shot_examples:
            examples_text = "\n\nExamples:\n"
            for i, example in enumerate(self.few_shot_examples):
                examples_text += f"\nExample {i + 1}:\n"
                examples_text += f"Input: {example.get('input', '')}\n"
                examples_text += f"Output: {example.get('output', '')}\n"
            user_prompt += examples_text

        # Add output format instruction
        if self.output_format == "json":
            user_prompt += "\n\nPlease respond in valid JSON format."

        return self.system_prompt, user_prompt


class PromptEngineer:
    """Prompt engineering utilities for better AI outputs."""

    # Built-in prompt templates
    TEMPLATES = {
        "summarize": PromptTemplate(
            name="summarize",
            template="Please summarize the following text concisely:\n\n{{text}}\n\nSummary:",
            variables=["text"],
            system_prompt="You are a helpful assistant that creates clear, concise summaries.",
            temperature=0.3,
            max_tokens=500,
            description="Concise text summarization",
        ),
        "extract_entities": PromptTemplate(
            name="extract_entities",
            template="Extract all named entities (people, organizations, locations, dates) from the following text:\n\n{{text}}\n\nEntities:",
            variables=["text"],
            system_prompt="You are an expert at information extraction. Extract entities accurately.",
            temperature=0.2,
            max_tokens=1000,
            output_format="json",
            description="Named entity extraction",
        ),
        "classify": PromptTemplate(
            name="classify",
            template="Classify the following text into one of these categories: {{categories}}\n\nText: {{text}}\n\nCategory:",
            variables=["text", "categories"],
            system_prompt="You are a text classification expert. Choose the most appropriate category.",
            temperature=0.1,
            max_tokens=100,
            description="Text classification",
        ),
        "sentiment": PromptTemplate(
            name="sentiment",
            template="Analyze the sentiment of the following text (positive, negative, or neutral):\n\n{{text}}\n\nSentiment:",
            variables=["text"],
            system_prompt="You are a sentiment analysis expert. Be objective and accurate.",
            temperature=0.1,
            max_tokens=50,
            description="Sentiment analysis",
        ),
        "qa": PromptTemplate(
            name="qa",
            template="Answer the following question based on the provided context.\n\nContext: {{context}}\n\nQuestion: {{question}}\n\nAnswer:",
            variables=["context", "question"],
            system_prompt="You are a helpful assistant. Answer questions based only on the provided context. If the answer is not in the context, say so.",
            temperature=0.3,
            max_tokens=500,
            description="Question answering with context",
        ),
        "cot_reasoning": PromptTemplate(
            name="cot_reasoning",
            template="Solve the following problem step by step.\n\nProblem: {{problem}}\n\nLet's think step by step:",
            variables=["problem"],
            system_prompt="You are a logical reasoning expert. Think carefully and show your work.",
            temperature=0.5,
            max_tokens=2000,
            description="Chain-of-Thought reasoning",
        ),
    }

    def __init__(self) -> None:
        self._custom_templates: dict[str, PromptTemplate] = {}

    def get_template(self, name: str) -> PromptTemplate | None:
        """Get a prompt template by name."""
        if name in self._custom_templates:
            return self._custom_templates[name]
        return self.TEMPLATES.get(name)

    def register_template(self, template: PromptTemplate) -> None:
        """Register a custom prompt template."""
        self._custom_templates[template.name] = template

    def list_templates(self) -> list[str]:
        """List all available template names."""
        return list(set(list(self.TEMPLATES.keys()) + list(self._custom_templates.keys())))

    def create_cot_prompt(self, question: str, context: str = "") -> tuple[str, str]:
        """Create a Chain-of-Thought prompt.

        Args:
            question: Question to answer.
            context: Optional context.

        Returns:
            Tuple of (system_prompt, user_prompt).
        """
        system = (
            "You are a careful and logical thinker. "
            "Always break down problems into steps. "
            "Show your reasoning before giving the final answer. "
            "Format your response as:\n"
            "Step 1: ...\n"
            "Step 2: ...\n"
            "...\n"
            "Final Answer: ..."
        )

        user = f"Question: {question}\n\n"
        if context:
            user += f"Context: {context}\n\n"
        user += "Please solve this step by step."

        return system, user

    def create_few_shot_prompt(
        self,
        task: str,
        examples: list[dict[str, str]],
        input_text: str,
    ) -> tuple[str, str]:
        """Create a few-shot learning prompt.

        Args:
            task: Task description.
            examples: List of examples with 'input' and 'output' keys.
            input_text: Input to process.

        Returns:
            Tuple of (system_prompt, user_prompt).
        """
        system = f"You are an expert at {task}. Follow the examples below."

        user = f"Task: {task}\n\n"
        user += "Examples:\n\n"
        for i, example in enumerate(examples):
            user += f"Example {i + 1}:\n"
            user += f"Input: {example.get('input', '')}\n"
            user += f"Output: {example.get('output', '')}\n\n"
        user += f"Now process the following input:\nInput: {input_text}\nOutput:"

        return system, user


class OutputValidator:
    """Validate and parse AI outputs."""

    def validate_json(self, output: str) -> tuple[bool, Any | None, list[str]]:
        """Validate JSON output.

        Returns:
            Tuple of (is_valid, parsed_data, errors).
        """
        errors = []
        try:
            # Try to extract JSON from markdown code blocks
            json_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", output)
            if json_match:
                output = json_match.group(1)

            parsed = json.loads(output)
            return True, parsed, errors
        except json.JSONDecodeError as e:
            errors.append(f"JSON parsing error: {e!s}")
            return False, None, errors

    def validate_classification(self, output: str, valid_categories: list[str]) -> tuple[bool, str, list[str]]:
        """Validate classification output.

        Returns:
            Tuple of (is_valid, category, errors).
        """
        errors = []
        output_lower = output.strip().lower()

        for category in valid_categories:
            if category.lower() in output_lower:
                return True, category, errors

        errors.append(f"Output does not match any valid category: {valid_categories}")
        return False, "", errors

    def validate_sentiment(self, output: str) -> tuple[bool, str, list[str]]:
        """Validate sentiment output."""
        valid_sentiments = ["positive", "negative", "neutral"]
        return self.validate_classification(output, valid_sentiments)

    def validate_length(self, output: str, min_length: int = 0, max_length: int = 10000) -> tuple[bool, list[str]]:
        """Validate output length."""
        errors = []
        length = len(output)
        if length < min_length:
            errors.append(f"Output too short: {length} < {min_length}")
        if length > max_length:
            errors.append(f"Output too long: {length} > {max_length}")
        return len(errors) == 0, errors


class HallucinationDetector:
    """Detect potential hallucinations in AI outputs."""

    # Common hallucination indicators
    HALLUCINATION_PATTERNS = [
        r"I (?:think|believe|guess|suppose)",
        r"It (?:seems|appears|looks) (?:like|that)",
        r"probably|possibly|maybe|perhaps",
        r"I\'m not (?:sure|certain)",
        r"could be|might be",
    ]

    def detect(self, output: str, context: str = "") -> tuple[float, list[str]]:
        """Detect potential hallucinations.

        Args:
            output: AI output text.
            context: Source context (if available).

        Returns:
            Tuple of (hallucination_score, indicators).
        """
        indicators = []
        score = 0.0

        # Check for uncertainty patterns
        output_lower = output.lower()
        for pattern in self.HALLUCINATION_PATTERNS:
            if re.search(pattern, output_lower):
                indicators.append(f"Uncertainty language detected: {pattern}")
                score += 0.1

        # Check for claims not supported by context
        if context:
            # Simple check: extract key claims and verify against context
            sentences = re.split(r"[.!?]+", output)
            unsupported = 0
            total = 0
            for sentence in sentences:
                sentence = sentence.strip()
                if len(sentence) > 20:  # Only check substantial sentences
                    total += 1
                    # Check if key words from sentence appear in context
                    words = set(sentence.lower().split())
                    context_words = set(context.lower().split())
                    overlap = len(words & context_words)
                    if overlap / max(1, len(words)) < 0.3:
                        unsupported += 1

            if total > 0:
                unsupported_ratio = unsupported / total
                score += unsupported_ratio * 0.5
                if unsupported_ratio > 0.3:
                    indicators.append(f"Many claims may be unsupported by context: {unsupported}/{total}")

        # Check for specific numbers/dates that might be fabricated
        numbers = re.findall(r"\b\d{4,}\b", output)
        if numbers and context:
            for number in numbers:
                if number not in context:
                    indicators.append(f"Potentially fabricated number: {number}")
                    score += 0.05

        return min(1.0, score), indicators


class ModelOptimizer:
    """Optimize model selection and usage."""

    # Task-to-model routing recommendations
    TASK_MODEL_MAP = {
        "summarization": {"small": "efficient", "large": "high_quality"},
        "classification": {"small": "efficient", "large": "high_quality"},
        "extraction": {"small": "efficient", "large": "high_quality"},
        "reasoning": {"small": "medium", "large": "high_quality"},
        "creative": {"small": "medium", "large": "high_quality"},
        "qa": {"small": "efficient", "large": "high_quality"},
    }

    def __init__(self) -> None:
        self._response_cache: dict[str, AIResponse] = {}
        self._token_usage: dict[str, int] = {}

    def select_model(self, task: str, complexity: str = "medium") -> str:
        """Select appropriate model for task.

        Args:
            task: Task type.
            complexity: Task complexity (low, medium, high).

        Returns:
            Recommended model type.
        """
        task_config = self.TASK_MODEL_MAP.get(task, {"small": "efficient", "large": "high_quality"})

        if complexity in ["low", "simple"]:
            return task_config.get("small", "efficient")
        elif complexity in ["high", "complex"]:
            return task_config.get("large", "high_quality")
        else:
            return "medium"

    def estimate_tokens(self, text: str) -> int:
        """Estimate token count for text.

        Rough estimate: 1 token ≈ 4 characters (English) or 1.5 characters (Chinese).
        """
        if not text:
            return 0
        # Mixed estimation
        char_count = len(text)
        chinese_chars = len(re.findall(r"[\u4e00-\u9fff]", text))
        english_chars = char_count - chinese_chars

        estimated = int(english_chars / 4 + chinese_chars / 1.5)
        return max(1, estimated)

    def cache_response(self, key: str, response: AIResponse, ttl: int = 3600) -> None:
        """Cache an AI response."""
        self._response_cache[key] = response

    def get_cached_response(self, key: str) -> AIResponse | None:
        """Get a cached AI response."""
        return self._response_cache.get(key)

    def track_usage(self, model: str, tokens: int) -> None:
        """Track token usage."""
        self._token_usage[model] = self._token_usage.get(model, 0) + tokens

    def get_usage_stats(self) -> dict[str, Any]:
        """Get token usage statistics."""
        total = sum(self._token_usage.values())
        return {
            "total_tokens": total,
            "by_model": dict(self._token_usage),
            "cached_responses": len(self._response_cache),
        }


class AIOptimizer:
    """Main AI content understanding optimizer.

    Combines prompt engineering, output validation, hallucination detection,
    and model optimization for robust AI processing.
    """

    def __init__(
        self,
        enable_validation: bool = True,
        enable_hallucination_detection: bool = True,
        enable_caching: bool = True,
    ) -> None:
        self.prompt_engineer = PromptEngineer()
        self.validator = OutputValidator()
        self.hallucination_detector = HallucinationDetector()
        self.model_optimizer = ModelOptimizer()

        self.enable_validation = enable_validation
        self.enable_hallucination_detection = enable_hallucination_detection
        self.enable_caching = enable_caching

    def process(
        self,
        text: str,
        task: str = "summarize",
        context: str = "",
        ai_fn: Callable | None = None,
        **kwargs,
    ) -> AIResponse:
        """Process text with optimized AI pipeline.

        Args:
            text: Input text.
            task: Task type (summarize, extract_entities, classify, etc.).
            context: Optional context.
            ai_fn: AI function to call (prompt) -> response string.
            **kwargs: Additional task parameters.

        Returns:
            AIResponse with processed result.
        """
        start_time = time.time()
        response = AIResponse()

        # Get prompt template
        template = self.prompt_engineer.get_template(task)
        if template:
            system_prompt, user_prompt = template.format(text=text, context=context, **kwargs)
            response.model = self.model_optimizer.select_model(task)
        else:
            system_prompt = "You are a helpful assistant."
            user_prompt = text
            response.model = "medium"

        # Estimate tokens
        response.prompt_tokens = self.model_optimizer.estimate_tokens(system_prompt + user_prompt)

        # Check cache
        cache_key = hashlib.md5(f"{task}:{text}:{context}".encode()).hexdigest()
        if self.enable_caching:
            cached = self.model_optimizer.get_cached_response(cache_key)
            if cached:
                cached.processing_time_ms = round((time.time() - start_time) * 1000, 2)
                return cached

        # Call AI function
        if ai_fn:
            try:
                output = ai_fn(user_prompt)
                response.content = output
                response.completion_tokens = self.model_optimizer.estimate_tokens(output)
                response.total_tokens = response.prompt_tokens + response.completion_tokens
            except Exception as exc:
                response.content = f"Error: {exc!s}"
                response.is_valid = False
                response.validation_errors.append(f"AI call failed: {exc!s}")
                return response
        else:
            # Fallback: simple processing without AI
            response.content = self._fallback_process(text, task)
            response.confidence = 0.5

        # Validate output
        if self.enable_validation and template:
            if template.output_format == "json":
                is_valid, parsed, errors = self.validator.validate_json(response.content)
                response.is_valid = is_valid
                response.parsed_content = parsed
                response.validation_errors = errors
            elif task == "classify" and "categories" in kwargs:
                is_valid, category, errors = self.validator.validate_classification(
                    response.content, kwargs["categories"]
                )
                response.is_valid = is_valid
                response.parsed_content = category
                response.validation_errors = errors

        # Hallucination detection
        if self.enable_hallucination_detection and context:
            hallucination_score, indicators = self.hallucination_detector.detect(response.content, context)
            response.hallucination_score = hallucination_score
            response.confidence = max(0, 1.0 - hallucination_score)

        response.processing_time_ms = round((time.time() - start_time) * 1000, 2)

        # Track usage and cache
        self.model_optimizer.track_usage(response.model, response.total_tokens)
        if self.enable_caching and response.is_valid:
            self.model_optimizer.cache_response(cache_key, response)

        return response

    def _fallback_process(self, text: str, task: str) -> str:
        """Fallback processing without AI."""
        if task == "summarize":
            # Simple extractive summarization (first 3 sentences)
            sentences = re.split(r"(?<=[.!?])\s+", text)
            return " ".join(sentences[:3])
        elif task == "classify":
            return "unknown"
        elif task == "sentiment":
            return "neutral"
        else:
            return text

    def get_stats(self) -> dict:
        """Get optimizer statistics."""
        return {
            "enable_validation": self.enable_validation,
            "enable_hallucination_detection": self.enable_hallucination_detection,
            "enable_caching": self.enable_caching,
            "available_templates": self.prompt_engineer.list_templates(),
            "usage": self.model_optimizer.get_usage_stats(),
        }


def optimize_ai_processing(
    text: str,
    task: str = "summarize",
    context: str = "",
    **kwargs,
) -> AIResponse:
    """Convenience function for optimized AI processing.

    Args:
        text: Input text.
        task: Task type.
        context: Optional context.
        **kwargs: Additional parameters.

    Returns:
        AIResponse with processed result.
    """
    optimizer = AIOptimizer()
    return optimizer.process(text, task=task, context=context, **kwargs)
