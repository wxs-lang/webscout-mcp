"""AI content processor for webscout-mcp.
Provides AI-powered content understanding capabilities:
- Text summarization
- Question answering (Q&A)
- Content classification and tagging
- Sentiment analysis
- Multi-document comparison

Supports multiple LLM backends:
- Ollama (local, free)
- OpenAI API
- Doubao (ByteDance) API
- Custom OpenAI-compatible API
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .logging_config import get_logger

log = get_logger(__name__)


@dataclass
class AIConfig:
    """Configuration for AI processor."""

    # Backend: ollama, openai, doubao, custom
    backend: str = "ollama"
    # Model name
    model: str = "qwen2.5:7b"
    # API base URL (for custom backend)
    api_base: str = ""
    # API key (for OpenAI/Doubao/custom)
    api_key: str = ""
    # Temperature for generation
    temperature: float = 0.7
    # Max tokens for generation
    max_tokens: int = 2000
    # Timeout in seconds
    timeout: float = 60.0
    # Whether to stream responses
    stream: bool = False

    @classmethod
    def from_env(cls) -> AIConfig:
        """Load configuration from environment variables."""
        import os

        return cls(
            backend=os.environ.get("WEBSCOUT_AI_BACKEND", "ollama"),
            model=os.environ.get("WEBSCOUT_AI_MODEL", "qwen2.5:7b"),
            api_base=os.environ.get("WEBSCOUT_AI_API_BASE", ""),
            api_key=os.environ.get("WEBSCOUT_AI_API_KEY", ""),
            temperature=float(os.environ.get("WEBSCOUT_AI_TEMPERATURE", "0.7")),
            max_tokens=int(os.environ.get("WEBSCOUT_AI_MAX_TOKENS", "2000")),
            timeout=float(os.environ.get("WEBSCOUT_AI_TIMEOUT", "60.0")),
        )


@dataclass
class AIResponse:
    """Response from AI processor."""

    content: str
    model: str = ""
    backend: str = ""
    usage: dict = field(default_factory=dict)
    error: str | None = None

    def to_dict(self) -> dict:
        return {
            "content": self.content,
            "model": self.model,
            "backend": self.backend,
            "usage": self.usage,
            "error": self.error,
        }


class AIProcessor:
    """AI content processor with multiple backend support.

    Supports:
    - Text summarization
    - Question answering
    - Content classification and tagging
    - Sentiment analysis
    - Multi-document comparison
    """

    def __init__(self, config: AIConfig | None = None) -> None:
        self.config = config or AIConfig.from_env()
        self._client = None

    def is_available(self) -> bool:
        """Check if AI backend is available."""
        if self.config.backend == "ollama":
            return self._check_ollama()
        elif self.config.backend in ("openai", "doubao", "custom"):
            return bool(self.config.api_key)
        return False

    def _check_ollama(self) -> bool:
        """Check if Ollama is available locally."""
        try:
            import httpx

            response = httpx.get("http://localhost:11434/api/tags", timeout=5.0)
            return response.status_code == 200
        except Exception:
            return False

    def _get_client(self):
        """Get or create LLM client."""
        if self._client:
            return self._client

        if self.config.backend == "ollama":
            self._client = self._create_ollama_client()
        elif self.config.backend == "openai":
            self._client = self._create_openai_client()
        elif self.config.backend == "doubao":
            self._client = self._create_doubao_client()
        elif self.config.backend == "custom":
            self._client = self._create_custom_client()
        else:
            raise ValueError(f"Unsupported backend: {self.config.backend}")

        return self._client

    def _create_ollama_client(self):
        """Create Ollama client."""
        try:
            import httpx

            return httpx.Client(
                base_url="http://localhost:11434",
                timeout=self.config.timeout,
            )
        except ImportError:
            raise ImportError("httpx is required for Ollama backend")

    def _create_openai_client(self):
        """Create OpenAI client."""
        try:
            from openai import OpenAI

            return OpenAI(
                api_key=self.config.api_key,
                base_url=self.config.api_base or None,
                timeout=self.config.timeout,
            )
        except ImportError:
            raise ImportError("openai is required for OpenAI backend")

    def _create_doubao_client(self):
        """Create Doubao (ByteDance) client."""
        try:
            from openai import OpenAI

            return OpenAI(
                api_key=self.config.api_key,
                base_url=self.config.api_base or "https://ark.cn-beijing.volces.com/api/v3",
                timeout=self.config.timeout,
            )
        except ImportError:
            raise ImportError("openai is required for Doubao backend")

    def _create_custom_client(self):
        """Create custom OpenAI-compatible client."""
        try:
            from openai import OpenAI

            return OpenAI(
                api_key=self.config.api_key,
                base_url=self.config.api_base,
                timeout=self.config.timeout,
            )
        except ImportError:
            raise ImportError("openai is required for custom backend")

    def _generate(self, prompt: str, system_prompt: str = "") -> AIResponse:
        """Generate response from LLM."""
        try:
            client = self._get_client()

            if self.config.backend == "ollama":
                return self._generate_ollama(client, prompt, system_prompt)
            else:
                return self._generate_openai(client, prompt, system_prompt)

        except Exception as exc:
            log.error("AI generation failed", extra={"error": str(exc), "backend": self.config.backend})
            return AIResponse(
                content="",
                model=self.config.model,
                backend=self.config.backend,
                error=f"{type(exc).__name__}: {exc}",
            )

    def _generate_ollama(self, client, prompt: str, system_prompt: str = "") -> AIResponse:
        """Generate using Ollama."""
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        response = client.post(
            "/api/chat",
            json={
                "model": self.config.model,
                "messages": messages,
                "stream": False,
                "options": {
                    "temperature": self.config.temperature,
                    "num_predict": self.config.max_tokens,
                },
            },
        )
        response.raise_for_status()
        data = response.json()

        return AIResponse(
            content=data.get("message", {}).get("content", ""),
            model=self.config.model,
            backend="ollama",
            usage=data.get("prompt_eval_count", 0) + data.get("eval_count", 0),
        )

    def _generate_openai(self, client, prompt: str, system_prompt: str = "") -> AIResponse:
        """Generate using OpenAI-compatible API."""
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        response = client.chat.completions.create(
            model=self.config.model,
            messages=messages,
            temperature=self.config.temperature,
            max_tokens=self.config.max_tokens,
            stream=False,
        )

        return AIResponse(
            content=response.choices[0].message.content,
            model=self.config.model,
            backend=self.config.backend,
            usage={
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens,
            },
        )

    def summarize(self, text: str, max_length: int = 500) -> AIResponse:
        """Summarize text content.

        Args:
            text: Text to summarize.
            max_length: Maximum summary length in characters.

        Returns:
            AIResponse with summary content.
        """
        system_prompt = "你是一个专业的文本摘要助手。请用简洁、准确的语言总结文本内容，保留关键信息。"
        prompt = f"请总结以下文本内容，不超过 {max_length} 字：\n\n{text}"
        return self._generate(prompt, system_prompt)

    def answer_question(self, context: str, question: str) -> AIResponse:
        """Answer a question based on context.

        Args:
            context: Context text to answer from.
            question: Question to answer.

        Returns:
            AIResponse with answer content.
        """
        system_prompt = "你是一个专业的问答助手。请根据提供的上下文内容回答问题，如果上下文中没有相关信息，请说明。"
        prompt = f"上下文：\n{context}\n\n问题：{question}\n\n请根据上下文回答问题。"
        return self._generate(prompt, system_prompt)

    def extract_key_points(self, text: str, num_points: int = 5) -> AIResponse:
        """Extract key points from text.

        Args:
            text: Text to extract from.
            num_points: Number of key points to extract.

        Returns:
            AIResponse with key points content.
        """
        system_prompt = "你是一个专业的信息提取助手。请从文本中提取关键要点，用编号列表形式输出。"
        prompt = f"请从以下文本中提取 {num_points} 个关键要点：\n\n{text}"
        return self._generate(prompt, system_prompt)

    def classify(self, text: str, categories: list[str]) -> AIResponse:
        """Classify text into categories.

        Args:
            text: Text to classify.
            categories: List of possible categories.

        Returns:
            AIResponse with classification result.
        """
        system_prompt = "你是一个专业的文本分类助手。请将文本分类到最合适的类别中，只输出类别名称。"
        categories_str = "、".join(categories)
        prompt = f"请将以下文本分类到以下类别之一（{categories_str}）：\n\n{text}"
        return self._generate(prompt, system_prompt)

    def generate_tags(self, text: str, num_tags: int = 5) -> AIResponse:
        """Generate tags for text.

        Args:
            text: Text to generate tags for.
            num_tags: Number of tags to generate.

        Returns:
            AIResponse with tags content.
        """
        system_prompt = "你是一个专业的标签生成助手。请为文本生成相关的标签，用逗号分隔，只输出标签。"
        prompt = f"请为以下文本生成 {num_tags} 个标签：\n\n{text}"
        return self._generate(prompt, system_prompt)

    def analyze_sentiment(self, text: str) -> AIResponse:
        """Analyze sentiment of text.

        Args:
            text: Text to analyze.

        Returns:
            AIResponse with sentiment analysis result.
        """
        system_prompt = "你是一个专业的情感分析助手。请分析文本的情感倾向，输出：正面、负面、中性，并简要说明理由。"
        prompt = f"请分析以下文本的情感倾向：\n\n{text}"
        return self._generate(prompt, system_prompt)

    def compare_documents(self, doc1: str, doc2: str, aspect: str = "整体") -> AIResponse:
        """Compare two documents.

        Args:
            doc1: First document content.
            doc2: Second document content.
            aspect: Aspect to compare (整体、内容、观点、结构等).

        Returns:
            AIResponse with comparison result.
        """
        system_prompt = "你是一个专业的文档对比助手。请对比两篇文档的异同点，分点说明。"
        prompt = f"请从{aspect}角度对比以下两篇文档：\n\n文档1：\n{doc1}\n\n文档2：\n{doc2}"
        return self._generate(prompt, system_prompt)

    def extract_entities(self, text: str) -> AIResponse:
        """Extract named entities from text.

        Args:
            text: Text to extract entities from.

        Returns:
            AIResponse with extracted entities.
        """
        system_prompt = (
            "你是一个专业的实体提取助手。请从文本中提取人名、地名、组织机构、时间、数字等实体，按类别分组输出。"
        )
        prompt = f"请从以下文本中提取实体：\n\n{text}"
        return self._generate(prompt, system_prompt)


def is_ai_available() -> bool:
    """Check if any AI backend is available."""
    processor = AIProcessor()
    return processor.is_available()


def get_available_backends() -> list[str]:
    """Get list of available AI backends."""
    backends = []
    # Check Ollama
    try:
        import httpx

        response = httpx.get("http://localhost:11434/api/tags", timeout=2.0)
        if response.status_code == 200:
            backends.append("ollama")
    except Exception:
        pass
    # Check API key based backends
    import os

    if os.environ.get("WEBSCOUT_AI_API_KEY"):
        backends.extend(["openai", "doubao", "custom"])
    return backends
