"""Metadata sanitization for WebResult.

Defines a single, explicit deny-list. Two layers:

  1. Exact-key deny list (case-insensitive) — obvious credential names.
  2. High-confidence substring match — catches common variants like
     ``auth_token``, ``x_api_key``, ``user_password``.

Conservative by design: if a key is ambiguous, we keep it. The cost of
dropping a useful field is lower than the cost of leaking a credential,
but we still want to avoid nuking legitimate metadata.

Values are never logged — only the key name is dropped.
"""

from __future__ import annotations

from typing import Any

# Exact keys (case-insensitive) that always get dropped.
_EXACT_DENY = frozenset(
    {
        "authorization",
        "proxy_authorization",
        "cookie",
        "cookies",
        "set_cookie",
        "token",
        "access_token",
        "refresh_token",
        "api_key",
        "apikey",
        "password",
        "passwd",
        "secret",
        "client_secret",
        "credential",
        "credentials",
    }
)

# High-confidence substrings (lower-cased, dashes normalized to underscores).
_KEYWORD_DENY = (
    "token",
    "secret",
    "password",
    "passwd",
    "credential",
    "apikey",
    "api_key",
)


def _normalize_key(k: str) -> str:
    return k.lower().replace("-", "_").replace(" ", "_")


def is_sensitive_key(k: str) -> bool:
    """Return True if *k* looks like a credential-bearing key."""
    if not isinstance(k, str):
        return False
    n = _normalize_key(k)
    if n in _EXACT_DENY:
        return True
    for kw in _KEYWORD_DENY:
        if kw in n:
            return True
    return False


def sanitize_metadata(metadata: dict[str, Any] | None) -> dict[str, Any]:
    """Return a copy of *metadata* with sensitive keys removed.

    Never mutates the input. Never raises. Non-string keys are dropped.
    """
    if not metadata:
        return {}
    out: dict[str, Any] = {}
    for k, v in metadata.items():
        if not isinstance(k, str):
            continue
        if is_sensitive_key(k):
            continue
        out[k] = v
    return out
