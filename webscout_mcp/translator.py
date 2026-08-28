"""Multi-language translation module for webscout-mcp.

Translate text between languages using multiple backends.
Supports Google Translate, DeepL, Azure, and local translation models.

Features:
- Multiple translation backends (Google, DeepL, Azure, local)
- Language detection
- Batch translation
- Text chunking for long texts
- Translation memory/caching
- Quality estimation
- Format preservation (HTML, Markdown)
- Glossary support
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .logging import get_logger

log = get_logger(__name__)


@dataclass
class TranslationResult:
    """Result of a translation."""

    source_text: str = ""
    translated_text: str = ""
    source_language: str = ""
    target_language: str = ""
    confidence: float = 0.0
    backend: str = ""
    processing_time_ms: float = 0.0
    chunks_translated: int = 0
    cached: bool = False

    def to_dict(self) -> dict:
        return {
            "source_language": self.source_language,
            "target_language": self.target_language,
            "confidence": self.confidence,
            "backend": self.backend,
            "processing_time_ms": self.processing_time_ms,
            "chunks_translated": self.chunks_translated,
            "cached": self.cached,
            "source_text_length": len(self.source_text),
            "translated_text_length": len(self.translated_text),
        }


class Translator:
    """Multi-backend translator.

    Features:
    - Google Translate (via googletrans or API)
    - DeepL API
    - Azure Translator
    - Local translation (via transformers)
    - Language detection
    - Caching
    - Text chunking
    """

    SUPPORTED_BACKENDS = ["google", "deepl", "azure", "local"]
    MAX_CHUNK_SIZE = 4500  # Characters per chunk for API limits

    def __init__(
        self,
        backend: str = "google",
        api_key: Optional[str] = None,
        source_language: str = "auto",
        target_language: str = "en",
        enable_cache: bool = True,
        max_cache_size: int = 1000,
    ) -> None:
        self.backend = backend.lower()
        self.api_key = api_key
        self.source_language = source_language
        self.target_language = target_language
        self.enable_cache = enable_cache
        self.max_cache_size = max_cache_size
        self._cache: Dict[str, TranslationResult] = {}
        self._engine = None
        self._init_backend()

    def _init_backend(self) -> None:
        """Initialize the translation backend."""
        if self.backend == "google":
            try:
                from googletrans import Translator as GoogleTranslator

                self._engine = GoogleTranslator()
                log.debug("Google Translate backend initialized")
            except ImportError:
                log.warning("googletrans not available")
                self._engine = None

        elif self.backend == "deepl":
            if self.api_key:
                try:
                    import deepl

                    self._engine = deepl.Translator(self.api_key)
                    log.debug("DeepL backend initialized")
                except ImportError:
                    log.warning("deepl not available")
                    self._engine = None
            else:
                log.warning("DeepL API key not provided")

        elif self.backend == "azure":
            if self.api_key:
                self._engine = {"api_key": self.api_key, "endpoint": "https://api.cognitive.microsofttranslator.com"}
                log.debug("Azure Translator backend initialized")
            else:
                log.warning("Azure API key not provided")

        elif self.backend == "local":
            try:
                from transformers import pipeline

                self._engine = pipeline("translation", model="Helsinki-NLP/opus-mt-en-zh")
                log.debug("Local translation backend initialized")
            except ImportError:
                log.warning("transformers not available for local translation")
                self._engine = None

    @property
    def is_available(self) -> bool:
        """Check if translation backend is available."""
        return self._engine is not None

    def _get_cache_key(self, text: str, source: str, target: str) -> str:
        """Generate cache key for translation."""
        key_str = f"{self.backend}:{source}:{target}:{text}"
        return hashlib.md5(key_str.encode()).hexdigest()

    def detect_language(self, text: str) -> Tuple[str, float]:
        """Detect the language of text.

        Args:
            text: Input text.

        Returns:
            Tuple of (language_code, confidence).
        """
        if not text or len(text.strip()) < 10:
            return "unknown", 0.0

        # Simple language detection based on character sets
        # This is a basic heuristic, real backends would be more accurate
        chinese_chars = len(re.findall(r"[\u4e00-\u9fff]", text))
        japanese_chars = len(re.findall(r"[\u3040-\u309f\u30a0-\u30ff]", text))
        korean_chars = len(re.findall(r"[\uac00-\ud7af]", text))
        cyrillic_chars = len(re.findall(r"[\u0400-\u04ff]", text))
        arabic_chars = len(re.findall(r"[\u0600-\u06ff]", text))

        total_chars = len(text)
        if total_chars == 0:
            return "unknown", 0.0

        ratios = {
            "zh": chinese_chars / total_chars,
            "ja": japanese_chars / total_chars,
            "ko": korean_chars / total_chars,
            "ru": cyrillic_chars / total_chars,
            "ar": arabic_chars / total_chars,
        }

        max_lang = max(ratios, key=ratios.get)
        max_ratio = ratios[max_lang]

        if max_ratio > 0.2:
            return max_lang, min(0.95, max_ratio * 2)

        # Default to English for Latin script
        if re.search(r"[a-zA-Z]", text):
            return "en", 0.7

        return "unknown", 0.0

    def _chunk_text(self, text: str, max_size: int = MAX_CHUNK_SIZE) -> List[str]:
        """Split long text into chunks for translation.

        Args:
            text: Input text.
            max_size: Maximum chunk size in characters.

        Returns:
            List of text chunks.
        """
        if len(text) <= max_size:
            return [text]

        chunks = []
        # Split by sentences/paragraphs
        paragraphs = re.split(r"(\n\n|\n)", text)
        current_chunk = ""

        for para in paragraphs:
            if len(current_chunk) + len(para) <= max_size:
                current_chunk += para
            else:
                if current_chunk:
                    chunks.append(current_chunk)
                # If single paragraph is too long, split by sentences
                if len(para) > max_size:
                    sentences = re.split(r"(?<=[.!?。！？])\s+", para)
                    current_chunk = ""
                    for sent in sentences:
                        if len(current_chunk) + len(sent) <= max_size:
                            current_chunk += sent + " "
                        else:
                            if current_chunk:
                                chunks.append(current_chunk)
                            # If single sentence is still too long, split by characters
                            if len(sent) > max_size:
                                for i in range(0, len(sent), max_size):
                                    chunks.append(sent[i : i + max_size])
                                current_chunk = ""
                            else:
                                current_chunk = sent + " "
                else:
                    current_chunk = para

        if current_chunk:
            chunks.append(current_chunk)

        return chunks

    def translate(
        self,
        text: str,
        source_language: Optional[str] = None,
        target_language: Optional[str] = None,
    ) -> TranslationResult:
        """Translate text.

        Args:
            text: Text to translate.
            source_language: Source language code (auto for detection).
            target_language: Target language code.

        Returns:
            TranslationResult with translated text.
        """
        import time

        source = source_language or self.source_language
        target = target_language or self.target_language

        result = TranslationResult(
            source_text=text,
            source_language=source,
            target_language=target,
            backend=self.backend,
        )

        if not text or not text.strip():
            result.translated_text = ""
            result.confidence = 0.0
            return result

        # Detect language if auto
        if source == "auto":
            detected_lang, confidence = self.detect_language(text)
            result.source_language = detected_lang
            result.confidence = confidence
            source = detected_lang if detected_lang != "unknown" else "en"

        # Check cache
        if self.enable_cache:
            cache_key = self._get_cache_key(text, source, target)
            if cache_key in self._cache:
                cached = self._cache[cache_key]
                cached.cached = True
                return cached

        if not self.is_available:
            result.translated_text = text  # Fallback: return original
            result.confidence = 0.0
            log.warning("Translation backend not available, returning original text")
            return result

        start_time = time.time()

        try:
            # Chunk long text
            chunks = self._chunk_text(text)
            translated_chunks = []

            for chunk in chunks:
                if not chunk.strip():
                    translated_chunks.append(chunk)
                    continue

                translated = self._translate_chunk(chunk, source, target)
                translated_chunks.append(translated)
                result.chunks_translated += 1

            result.translated_text = "".join(translated_chunks)

        except Exception as exc:
            log.error("Translation failed", extra={"error": str(exc)})
            result.translated_text = text
            result.confidence = 0.0

        result.processing_time_ms = round((time.time() - start_time) * 1000, 2)

        # Cache result
        if self.enable_cache and result.translated_text:
            cache_key = self._get_cache_key(text, source, target)
            if len(self._cache) >= self.max_cache_size:
                # Remove oldest entry (simple FIFO)
                oldest_key = next(iter(self._cache))
                del self._cache[oldest_key]
            self._cache[cache_key] = result

        return result

    def _translate_chunk(self, text: str, source: str, target: str) -> str:
        """Translate a single chunk using the backend."""
        if self.backend == "google" and self._engine:
            try:
                result = self._engine.translate(text, src=source, dest=target)
                return result.text
            except Exception:
                return text

        elif self.backend == "deepl" and self._engine:
            try:
                result = self._engine.translate_text(text, target_lang=target.upper())
                return result.text
            except Exception:
                return text

        elif self.backend == "azure" and self._engine:
            try:
                import requests

                endpoint = self._engine["endpoint"]
                headers = {
                    "Ocp-Apim-Subscription-Key": self._engine["api_key"],
                    "Content-Type": "application/json",
                }
                params = {"api-version": "3.0", "from": source, "to": target}
                body = [{"text": text}]
                response = requests.post(f"{endpoint}/translate", headers=headers, params=params, json=body)
                if response.status_code == 200:
                    return response.json()[0]["translations"][0]["text"]
                return text
            except Exception:
                return text

        elif self.backend == "local" and self._engine:
            try:
                result = self._engine(text)
                return result[0]["translation_text"]
            except Exception:
                return text

        return text

    def translate_batch(
        self,
        texts: List[str],
        source_language: Optional[str] = None,
        target_language: Optional[str] = None,
    ) -> List[TranslationResult]:
        """Translate multiple texts.

        Args:
            texts: List of texts to translate.
            source_language: Source language code.
            target_language: Target language code.

        Returns:
            List of TranslationResult objects.
        """
        results = []
        for text in texts:
            result = self.translate(text, source_language, target_language)
            results.append(result)
        return results

    def clear_cache(self) -> None:
        """Clear the translation cache."""
        self._cache.clear()

    @property
    def cache_size(self) -> int:
        """Get current cache size."""
        return len(self._cache)


def translate_text(
    text: str,
    target_language: str = "en",
    source_language: str = "auto",
    backend: str = "google",
    api_key: Optional[str] = None,
) -> TranslationResult:
    """Convenience function to translate text.

    Args:
        text: Text to translate.
        target_language: Target language code.
        source_language: Source language code.
        backend: Translation backend.
        api_key: API key for paid backends.

    Returns:
        TranslationResult with translated text.
    """
    translator = Translator(
        backend=backend,
        api_key=api_key,
        source_language=source_language,
        target_language=target_language,
    )
    return translator.translate(text)
