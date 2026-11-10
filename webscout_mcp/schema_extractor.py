"""Schema-driven extraction without an LLM.

## Why this shape

Firecrawl's `formats: [{type: "json", schema: {...}}]` lets a caller describe the data it
wants and get back a matching object. That is the most-used capability in the comparable
project, because callers know what they want, not where it lives.

Two ways to implement it: call an LLM, or derive it. The operator chose derivation - no API
key, no per-call cost, deterministic output. The tradeoff is honest: a derived mapping cannot
handle a page whose structure it has never seen, which is why every field carries the source
it was resolved from.

## Resolution order, best first

1. **JSON-LD** - the page states its own structured data; nothing is guessed. `@type`,
   `name`, `price`, `author`, `datePublished` and friends map directly.
2. **Meta tags** - OpenGraph and Twitter cards. `og:title` for `title`, `og:image` for
   `image`, `article:published_time` for a date.
3. **Semantic HTML** - `<h1>`, `<article>`, `<time datetime>`, `itemprop`, and a small set of
   class-name hints (`price`, `author`, `date`).

Anything still unresolved is `null` with a `missing` note, never a guess. A caller that gets
`null` knows to try something else; a caller that gets a wrong value does not.

## Why `source` is recorded per field

The difference between "the page said this in JSON-LD" and "we found this in an `<h1>`" is
the difference between trustworthy and approximate. Recording it lets a caller decide whether
to trust a field, and lets a failure be diagnosed instead of merely observed - the same
principle `recovery_outcome` applies to fetches.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from bs4 import BeautifulSoup

from .logging_config import get_logger
from .metadata_extractor import extract_metadata

log = get_logger(__name__)

# How a value was obtained. Ordered by trustworthiness, which is also the resolution order.
SOURCE_JSON_LD = "json-ld"
SOURCE_META = "meta"
SOURCE_SEMANTIC = "semantic-html"
SOURCE_NONE = ""

# JSON-LD keys that commonly carry the value a caller asks for by a shorter name.
_JSON_LD_ALIASES: dict[str, tuple[str, ...]] = {
    "title": ("name", "headline"),
    "name": ("name", "headline"),
    "description": ("description", "abstract"),
    "price": ("price", "lowPrice", "highPrice"),
    "currency": ("priceCurrency",),
    "author": ("author", "creator"),
    "date": ("datePublished", "dateCreated", "uploadDate"),
    "image": ("image", "thumbnailUrl"),
    "url": ("url", "@id"),
    "rating": ("ratingValue", "reviewRating"),
    "brand": ("brand", "manufacturer"),
}

# Meta keys that carry a value, per requested field.
_META_ALIASES: dict[str, tuple[str, ...]] = {
    "title": ("og:title", "twitter:title"),
    "name": ("og:title", "twitter:title"),
    "description": ("og:description", "twitter:description", "description"),
    "image": ("og:image", "twitter:image"),
    "url": ("og:url",),
    "date": ("article:published_time", "article:modified_time"),
    "author": ("article:author", "twitter:creator"),
    "site_name": ("og:site_name",),
}

# Class-name fragments that usually mark a field, used only when nothing better resolved.
_CLASS_HINTS: dict[str, tuple[str, ...]] = {
    "price": ("price", "cost", "amount", "money"),
    "author": ("author", "byline", "writer"),
    "date": ("date", "time", "published", "posted"),
    "title": ("title", "headline", "heading"),
    "description": ("description", "summary", "excerpt", "intro"),
    "rating": ("rating", "stars", "score"),
}


@dataclass
class FieldResult:
    """One resolved field, with where it came from."""

    value: Any = None
    source: str = SOURCE_NONE

    @property
    def found(self) -> bool:
        return self.source != SOURCE_NONE


@dataclass
class SchemaResult:
    """The extracted object plus per-field provenance."""

    url: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    sources: dict[str, str] = field(default_factory=dict)
    missing: list[str] = field(default_factory=list)

    @property
    def resolved(self) -> int:
        return len(self.data) - len(self.missing)

    def to_dict(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "data": self.data,
            "sources": self.sources,
            "missing": self.missing,
            "resolved": self.resolved,
            "requested": len(self.data),
        }


def _flatten_json_ld(items: list[dict]) -> dict[str, Any]:
    """Merge JSON-LD blocks into one mapping.

    Pages nest the interesting values (`author: {name: ...}`) and split them across blocks
    (`@graph`). Flattening first means the alias lookup does not have to know the shape.
    """
    flat: dict[str, Any] = {}

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if key == "@graph" and isinstance(value, list):
                    for entry in value:
                        walk(entry)
                    continue
                if key not in flat and not isinstance(value, (dict, list)):
                    flat[key] = value
                elif isinstance(value, dict):
                    # Nested objects commonly carry `name`; lift it for alias lookup.
                    inner = value.get("name")
                    if inner is not None and key not in flat:
                        flat[key] = inner
                    walk(value)
                elif isinstance(value, list) and value:
                    first = value[0]
                    if isinstance(first, dict) and "name" in first and key not in flat:
                        flat[key] = first["name"]
                    walk(first)
        elif isinstance(node, list):
            for entry in node:
                walk(entry)

    for item in items:
        walk(item)
    return flat


def _semantic_lookup(soup: BeautifulSoup, name: str) -> Any:
    """Last resort: semantic markup, then a narrow class-name hint."""
    lowered = name.lower()

    if lowered in ("title", "name", "headline"):
        for tag in ("h1", "h2"):
            node = soup.find(tag)
            if node and node.get_text(strip=True):
                return node.get_text(strip=True)

    if lowered in ("date", "published", "datepublished"):
        node = soup.find("time")
        if node:
            if node.get("datetime"):
                return node["datetime"]
            text = node.get_text(strip=True)
            if text:
                return text
        node = soup.find(attrs={"itemprop": re.compile("date", re.IGNORECASE)})
        if node:
            return node.get("content") or node.get_text(strip=True)

    if lowered in ("description", "summary", "excerpt"):
        node = soup.find("article")
        if node:
            text = node.get_text(" ", strip=True)
            if text:
                return text[:400]

    for hint in _CLASS_HINTS.get(lowered, ()):
        node = soup.find(class_=re.compile(hint, re.IGNORECASE))
        if node:
            text = node.get("content") or node.get_text(" ", strip=True)
            if text:
                return text.strip()[:300]

    node = soup.find(attrs={"itemprop": re.compile(f"^{re.escape(name)}$", re.IGNORECASE)})
    if node:
        return node.get("content") or node.get_text(strip=True)

    return None


def _coerce(value: Any, declared: str | None) -> Any:
    """Convert to the type the schema asked for, or leave as-is when it cannot be.

    A conversion that fails returns the original rather than None: showing the caller the
    raw string lets them see what the page actually said.
    """
    if value is None or not declared:
        return value
    try:
        if declared in ("number", "integer"):
            if isinstance(value, (int, float)):
                return int(value) if declared == "integer" else float(value)
            text = str(value).replace(",", "").replace("$", "").replace("¥", "").strip()
            match = re.search(r"-?\d+(?:\.\d+)?", text)
            if match:
                num = float(match.group(0))
                return int(num) if declared == "integer" else num
            return value
        if declared == "boolean":
            if isinstance(value, bool):
                return value
            return str(value).strip().lower() in ("true", "1", "yes", "y")
        if declared == "string":
            return str(value)
        if declared == "array":
            return value if isinstance(value, list) else [value]
    except (TypeError, ValueError):
        return value
    return value


def extract_by_schema(
    html: str,
    schema: dict[str, Any],
    base_url: str = "",
) -> SchemaResult:
    """Resolve each schema property against the page, honouring the declared types.

    `schema` is a JSON-Schema-like object: `{"type": "object", "properties": {...}}`. Only
    `properties` and each property's `type` are used; other keywords are ignored rather than
    rejected, so a caller can pass a schema it already had.
    """
    result = SchemaResult(url=base_url)
    if not html:
        return result

    properties = (schema or {}).get("properties") or {}
    if not isinstance(properties, dict):
        return result

    try:
        soup = BeautifulSoup(html, "html.parser")
    except Exception:  # noqa: BLE001 - malformed HTML must not raise
        log.debug("schema extraction: html parse failed", exc_info=True)
        soup = None

    try:
        meta = extract_metadata(html, base_url)
    except Exception:  # noqa: BLE001
        log.debug("schema extraction: metadata extraction failed", exc_info=True)
        meta = None

    json_ld = _flatten_json_ld(meta.json_ld) if meta and meta.json_ld else {}
    raw_meta = dict(meta.raw_meta) if meta else {}

    def resolve(name: str) -> FieldResult:
        # 1) the page's own structured data
        for alias in _JSON_LD_ALIASES.get(name.lower(), (name,)):
            if alias in json_ld and json_ld[alias] not in ("", None):
                return FieldResult(json_ld[alias], SOURCE_JSON_LD)

        # 2) declared metadata
        for key in _META_ALIASES.get(name.lower(), ()):
            value = raw_meta.get(key)
            if value:
                return FieldResult(value, SOURCE_META)
        if meta is not None:
            direct = getattr(meta, name.lower(), None)
            if isinstance(direct, str) and direct:
                return FieldResult(direct, SOURCE_META)

        # 3) semantics
        if soup is not None:
            found = _semantic_lookup(soup, name)
            if found:
                return FieldResult(found, SOURCE_SEMANTIC)

        return FieldResult()

    for name, spec in properties.items():
        declared = spec.get("type") if isinstance(spec, dict) else None
        found = resolve(name)
        if found.found:
            result.data[name] = _coerce(found.value, declared)
            result.sources[name] = found.source
        else:
            result.data[name] = None
            result.sources[name] = SOURCE_NONE
            result.missing.append(name)

    return result


__all__ = [
    "FieldResult",
    "SchemaResult",
    "SOURCE_JSON_LD",
    "SOURCE_META",
    "SOURCE_SEMANTIC",
    "extract_by_schema",
]
