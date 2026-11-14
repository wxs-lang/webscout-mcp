"""Select a value out of a JSON document for change monitoring.

Two selector languages, chosen by prefix on the expression::

    json:$.product.price      JSONPath (always available)
    jq:.product.price         jq (requires the [json] extra)

A bare expression without a prefix is treated as JSONPath, since that is the light
dependency and the common case.

The result is always a string, because monitoring compares text: reducing the selection
to one value is what makes an API response stable enough to watch, and it lets the
existing diff and noise filters apply unchanged.
"""

from __future__ import annotations

import json
from typing import Any

__all__ = [
    "JSON_SELECTOR_PREFIXES",
    "SelectError",
    "available_languages",
    "extract",
    "parse_selector",
]

JSON_SELECTOR_PREFIXES = ("json:", "jq:")

_JSONPATH_HINT = "JSONPath selection needs the 'jsonpath' package. Install it with: pip install 'webscout-mcp[json]'"
_JQ_HINT = "jq selection needs the 'jq' package. Install it with: pip install 'webscout-mcp[json]'"


class SelectError(ValueError):
    """A selector could not be applied; the message says how to fix it."""


def _has_module(name: str) -> bool:
    import importlib.util

    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def available_languages() -> dict[str, bool]:
    """Which selector languages this installation can run.

    Used by the tool description and by error messages so a caller learns what is
    possible without reading the changelog.
    """
    return {"jsonpath": _has_module("jsonpath"), "jq": _has_module("jq")}


def parse_selector(selector: str) -> tuple[str, str]:
    """Split ``language:expression`` into its parts.

    Args:
        selector: e.g. ``json:$.a.b`` or ``jq:.a.b``.

    Returns:
        ``(language, expression)`` where language is ``"jsonpath"`` or ``"jq"``.

    Raises:
        SelectError: for an empty selector or an unknown prefix.
    """
    text = (selector or "").strip()
    if not text:
        raise SelectError("empty JSON selector")

    lowered = text.lower()
    if lowered.startswith("json:"):
        expression = text[len("json:") :].strip()
        if not expression:
            raise SelectError("json: selector is missing an expression")
        return "jsonpath", expression
    if lowered.startswith("jq:"):
        expression = text[len("jq:") :].strip()
        if not expression:
            raise SelectError("jq: selector is missing an expression")
        return "jq", expression

    # No prefix: JSONPath is the default because it is the light dependency.
    return "jsonpath", text


def _load_document(raw: str) -> Any:
    """Parse the response body, tolerating leading whitespace and a BOM."""
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SelectError(
            f"response is not valid JSON ({exc.msg} at position {exc.pos}); a JSON selector needs a JSON body"
        ) from exc


def _extract_jsonpath(document: Any, expression: str) -> list[Any]:
    try:
        import jsonpath
    except ImportError as exc:  # pragma: no cover - dependency declared in [json]
        raise SelectError(_JSONPATH_HINT) from exc

    try:
        matches = jsonpath.jsonpath(document, expression)
    except Exception as exc:  # noqa: BLE001 - the library raises assorted types
        raise SelectError(f"invalid JSONPath {expression!r}: {exc}") from exc

    # `jsonpath.jsonpath` returns False when nothing matches.
    if not matches:
        return []

    # Malformed JSONPath is not always an error: measured, `$[[[` returns the whole
    # document followed by every node inside it (10 matches on a small document), because
    # the library degrades the bad syntax into a wildcard. For a monitor that means
    # silently watching the entire response instead of one field.
    #
    # The reliable signature is the document itself appearing first in a multi-match
    # result. Checked against the alternatives: `$..*` returns its nodes without the
    # document first, and every ordinary selector returns one or two values.
    if len(matches) > 1 and matches[0] == document:
        raise SelectError(
            f"JSONPath {expression!r} matched the whole document plus its contents, "
            "which means the expression is malformed and was read as a wildcard. "
            "Name the field explicitly, for example $.product.price"
        )

    return list(matches)


def _extract_jq(document: Any, expression: str) -> list[Any]:
    try:
        import jq
    except ImportError as exc:
        raise SelectError(_JQ_HINT) from exc

    try:
        compiled = jq.compile(expression)
        results = compiled.input(document).all()
    except Exception as exc:  # noqa: BLE001 - jq raises its own error type
        raise SelectError(f"invalid jq expression {expression!r}: {exc}") from exc

    # jq yields None for a missing path rather than an empty result set; treat that as
    # no match so it is not mistaken for a value of null.
    return [value for value in results if value is not None]


def extract(raw: str, selector: str) -> str:
    """Apply a selector to a JSON document and return the selected value as text.

    A single match is rendered as its scalar value; multiple matches are rendered as a
    JSON array, so a list that grows or shrinks registers as a change.

    Args:
        raw: Response body, expected to be JSON.
        selector: ``json:...``, ``jq:...``, or a bare JSONPath expression.

    Returns:
        The selected value as a string.

    Raises:
        SelectError: with an actionable message if the selector cannot be applied, the
            body is not JSON, or nothing matched.
    """
    language, expression = parse_selector(selector)
    document = _load_document(raw)

    if language == "jq":
        matches = _extract_jq(document, expression)
    else:
        matches = _extract_jsonpath(document, expression)

    if not matches:
        raise SelectError(
            f"selector {selector!r} matched nothing in the response; check the path against the actual document"
        )

    if len(matches) == 1:
        value = matches[0]
        if isinstance(value, str):
            return value
        return json.dumps(value, ensure_ascii=False, sort_keys=True)

    return json.dumps(matches, ensure_ascii=False, sort_keys=True)
