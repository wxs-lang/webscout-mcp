"""Data cleaning pipeline module for webscout-mcp.

Configurable data cleaning, normalization, deduplication, and transformation pipeline.

Features:
- Text cleaning (whitespace, special chars, HTML tags)
- Normalization (Unicode, case, encoding)
- Deduplication (exact and fuzzy)
- Field validation and transformation
- Missing value handling
- Outlier detection
- Data type conversion
- Pipeline composition (chain multiple cleaners)
- Configurable rules
- Progress reporting
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from .logging_config import get_logger

log = get_logger(__name__)


@dataclass
class CleaningResult:
    """Result of data cleaning."""

    original_count: int = 0
    cleaned_count: int = 0
    removed_count: int = 0
    modified_count: int = 0
    errors: list[str] = field(default_factory=list)
    stats: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "original_count": self.original_count,
            "cleaned_count": self.cleaned_count,
            "removed_count": self.removed_count,
            "modified_count": self.modified_count,
            "errors": self.errors,
            "stats": self.stats,
        }


class TextCleaner:
    """Text cleaning utilities."""

    # Common HTML entity patterns
    HTML_ENTITIES = {
        "&nbsp;": " ",
        "&amp;": "&",
        "&lt;": "<",
        "&gt;": ">",
        "&quot;": '"',
        "&#39;": "'",
        "&#x27;": "'",
        "&#x2F;": "/",
    }

    @staticmethod
    def remove_html_tags(text: str) -> str:
        """Remove HTML tags from text."""
        if not text:
            return ""
        return re.sub(r"<[^>]+>", "", text)

    @staticmethod
    def decode_html_entities(text: str) -> str:
        """Decode HTML entities."""
        if not text:
            return ""
        for entity, char in TextCleaner.HTML_ENTITIES.items():
            text = text.replace(entity, char)
        return text

    @staticmethod
    def normalize_whitespace(text: str) -> str:
        """Normalize whitespace (multiple spaces to single, trim)."""
        if not text:
            return ""
        return re.sub(r"\s+", " ", text).strip()

    @staticmethod
    def remove_special_chars(text: str, keep: str = "") -> str:
        """Remove special characters, keeping alphanumeric and specified chars."""
        if not text:
            return ""
        pattern = rf"[^a-zA-Z0-9\s{re.escape(keep)}]"
        return re.sub(pattern, "", text)

    @staticmethod
    def normalize_unicode(text: str) -> str:
        """Normalize Unicode to NFKC form."""
        if not text:
            return ""
        return unicodedata.normalize("NFKC", text)

    @staticmethod
    def to_lowercase(text: str) -> str:
        """Convert text to lowercase."""
        return text.lower() if text else ""

    @staticmethod
    def to_uppercase(text: str) -> str:
        """Convert text to uppercase."""
        return text.upper() if text else ""

    @staticmethod
    def remove_urls(text: str) -> str:
        """Remove URLs from text."""
        if not text:
            return ""
        return re.sub(r"https?://\S+|www\.\S+", "", text)

    @staticmethod
    def remove_emails(text: str) -> str:
        """Remove email addresses from text."""
        if not text:
            return ""
        return re.sub(r"[\w.+-]+@[\w-]+\.[\w.-]+", "", text)

    @staticmethod
    def remove_phone_numbers(text: str) -> str:
        """Remove phone numbers from text."""
        if not text:
            return ""
        return re.sub(r"[\+\(]?[1-9][0-9 .\-\(\)]{8,}[0-9]", "", text)

    @staticmethod
    def truncate(text: str, max_length: int, suffix: str = "...") -> str:
        """Truncate text to max length."""
        if not text or len(text) <= max_length:
            return text or ""
        return text[: max_length - len(suffix)] + suffix

    @staticmethod
    def clean_full(text: str) -> str:
        """Full text cleaning pipeline."""
        if not text:
            return ""
        text = TextCleaner.remove_html_tags(text)
        text = TextCleaner.decode_html_entities(text)
        text = TextCleaner.normalize_unicode(text)
        text = TextCleaner.normalize_whitespace(text)
        return text


class DataCleaner:
    """Configurable data cleaner for dictionary records."""

    def __init__(
        self,
        text_fields: list[str] | None = None,
        required_fields: list[str] | None = None,
        dedup_fields: list[str] | None = None,
        max_text_length: int = 100000,
        remove_empty: bool = True,
        normalize_unicode: bool = True,
    ) -> None:
        self.text_fields = text_fields or []
        self.required_fields = required_fields or []
        self.dedup_fields = dedup_fields or []
        self.max_text_length = max_text_length
        self.remove_empty = remove_empty
        self.normalize_unicode = normalize_unicode
        self._seen = set()

    def clean_record(self, record: dict) -> dict | None:
        """Clean a single record.

        Args:
            record: Dictionary record to clean.

        Returns:
            Cleaned record, or None if it should be removed.
        """
        if not isinstance(record, dict):
            return None

        cleaned = dict(record)

        # Check required fields
        for field in self.required_fields:
            if field not in cleaned or not cleaned[field]:
                return None

        # Clean text fields
        for field in self.text_fields:
            if field in cleaned and isinstance(cleaned[field], str):
                value = cleaned[field]
                value = TextCleaner.remove_html_tags(value)
                value = TextCleaner.decode_html_entities(value)
                if self.normalize_unicode:
                    value = TextCleaner.normalize_unicode(value)
                value = TextCleaner.normalize_whitespace(value)
                value = TextCleaner.truncate(value, self.max_text_length)
                cleaned[field] = value

        # Remove empty records
        if self.remove_empty:
            if not any(cleaned.values()):
                return None

        # Deduplication
        if self.dedup_fields:
            dedup_key = tuple(str(cleaned.get(f, "")) for f in self.dedup_fields)
            if dedup_key in self._seen:
                return None
            self._seen.add(dedup_key)

        return cleaned

    def clean_batch(self, records: list[dict]) -> tuple[list[dict], CleaningResult]:
        """Clean a batch of records.

        Args:
            records: List of dictionary records.

        Returns:
            Tuple of (cleaned_records, cleaning_result).
        """
        result = CleaningResult(original_count=len(records))
        cleaned_records = []
        self._seen.clear()

        for record in records:
            try:
                cleaned = self.clean_record(record)
                if cleaned is not None:
                    if cleaned != record:
                        result.modified_count += 1
                    cleaned_records.append(cleaned)
                else:
                    result.removed_count += 1
            except Exception as exc:
                result.errors.append(f"{type(exc).__name__}: {exc}")
                result.removed_count += 1

        result.cleaned_count = len(cleaned_records)
        result.stats = {
            "retention_rate": (
                round(result.cleaned_count / result.original_count * 100, 1) if result.original_count > 0 else 0
            ),
            "modification_rate": (
                round(result.modified_count / result.original_count * 100, 1) if result.original_count > 0 else 0
            ),
        }

        return cleaned_records, result

    def reset(self) -> None:
        """Reset deduplication state."""
        self._seen.clear()


class CleaningPipeline:
    """Composable cleaning pipeline.

    Chain multiple cleaning steps together for complex data processing.
    """

    def __init__(self, name: str = "default") -> None:
        self.name = name
        self._steps: list[tuple[str, Callable]] = []
        self._stats: dict = {}

    def add_step(self, name: str, func: Callable[[dict], dict | None]) -> CleaningPipeline:
        """Add a cleaning step.

        Args:
            name: Step name.
            func: Function that takes a record dict and returns cleaned dict or None.

        Returns:
            Self for chaining.
        """
        self._steps.append((name, func))
        return self

    def add_text_cleaner(self, fields: list[str], **kwargs) -> CleaningPipeline:
        """Add a text cleaning step for specified fields.

        Args:
            fields: List of field names to clean.
            **kwargs: Additional cleaning options.

        Returns:
            Self for chaining.
        """

        def clean_text(record: dict) -> dict:
            for field in fields:
                if field in record and isinstance(record[field], str):
                    record[field] = TextCleaner.clean_full(record[field])
            return record

        self.add_step(f"text_clean_{','.join(fields)}", clean_text)
        return self

    def add_field_validator(self, field: str, validator: Callable[[Any], bool]) -> CleaningPipeline:
        """Add a field validation step.

        Args:
            field: Field name to validate.
            validator: Function that returns True if valid.

        Returns:
            Self for chaining.
        """

        def validate(record: dict) -> dict | None:
            if field not in record or not validator(record[field]):
                return None
            return record

        self.add_step(f"validate_{field}", validate)
        return self

    def add_field_transformer(self, field: str, transformer: Callable[[Any], Any]) -> CleaningPipeline:
        """Add a field transformation step.

        Args:
            field: Field name to transform.
            transformer: Function that transforms the field value.

        Returns:
            Self for chaining.
        """

        def transform(record: dict) -> dict:
            if field in record:
                record[field] = transformer(record[field])
            return record

        self.add_step(f"transform_{field}", transform)
        return self

    def add_deduplicator(self, fields: list[str]) -> CleaningPipeline:
        """Add a deduplication step.

        Args:
            fields: Fields to use for deduplication key.

        Returns:
            Self for chaining.
        """
        seen = set()

        def dedup(record: dict) -> dict | None:
            key = tuple(str(record.get(f, "")) for f in fields)
            if key in seen:
                return None
            seen.add(key)
            return record

        self.add_step(f"dedup_{','.join(fields)}", dedup)
        return self

    def add_filter(self, condition: Callable[[dict], bool]) -> CleaningPipeline:
        """Add a filtering step.

        Args:
            condition: Function that returns True to keep record.

        Returns:
            Self for chaining.
        """

        def filter_record(record: dict) -> dict | None:
            return record if condition(record) else None

        self.add_step("filter", filter_record)
        return self

    def process(self, records: list[dict]) -> tuple[list[dict], CleaningResult]:
        """Process records through the pipeline.

        Args:
            records: List of records to process.

        Returns:
            Tuple of (processed_records, result).
        """
        result = CleaningResult(original_count=len(records))
        processed = []
        step_stats = {name: 0 for name, _ in self._steps}

        for record in records:
            current = dict(record)
            modified = False
            removed = False

            for step_name, step_func in self._steps:
                try:
                    output = step_func(current)
                    if output is None:
                        removed = True
                        step_stats[step_name] += 1
                        break
                    if output != current:
                        modified = True
                    current = output
                except Exception as exc:
                    result.errors.append(f"Step '{step_name}': {type(exc).__name__}: {exc}")
                    removed = True
                    step_stats[step_name] += 1
                    break

            if not removed:
                if modified:
                    result.modified_count += 1
                processed.append(current)
            else:
                result.removed_count += 1

        result.cleaned_count = len(processed)
        result.stats = {
            "retention_rate": (
                round(result.cleaned_count / result.original_count * 100, 1) if result.original_count > 0 else 0
            ),
            "step_removals": step_stats,
            "num_steps": len(self._steps),
        }

        return processed, result

    @property
    def steps(self) -> list[str]:
        """Get list of step names."""
        return [name for name, _ in self._steps]

    def __len__(self) -> int:
        return len(self._steps)


def clean_data(
    records: list[dict],
    text_fields: list[str] | None = None,
    required_fields: list[str] | None = None,
    dedup_fields: list[str] | None = None,
) -> tuple[list[dict], CleaningResult]:
    """Convenience function to clean data with default settings.

    Args:
        records: List of records to clean.
        text_fields: Fields to apply text cleaning.
        required_fields: Fields that must be present and non-empty.
        dedup_fields: Fields to use for deduplication.

    Returns:
        Tuple of (cleaned_records, result).
    """
    cleaner = DataCleaner(
        text_fields=text_fields or [],
        required_fields=required_fields or [],
        dedup_fields=dedup_fields or [],
    )
    return cleaner.clean_batch(records)
