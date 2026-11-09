"""Unified DecisionEvent model for Fetch + Search production decisions.

A DecisionEvent records *what the deterministic recovery system decided* and
*what actually happened*, using only sanitized scalars and hashes. It never
stores full HTML, full body text, raw query strings, Authorization headers,
cookies, tokens, API keys, or credentials.

This is the data layer that future offline evaluation (and any potential
Jev Advisory Mode decision) must be grounded in. Jev predictions are joined
by trace_id / run_id, never stored as ground truth.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import time
import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


class DecisionDomain(str, Enum):
    FETCH = "fetch"
    SEARCH = "search"


class DecisionStage(str, Enum):
    PRIMARY = "primary"
    RECOVERY = "recovery"
    FINAL = "final"


# Labels that may be attached by humans or objective fixtures. These are
# intentionally NOT Jev-verified.
class LabelSource(str, Enum):
    DETERMINISTIC_FIXTURE = "deterministic_fixture"
    HUMAN_VERIFIED = "human_verified"
    OBJECTIVE_OUTCOME = "objective_outcome"
    HISTORICAL_VERIFIED = "historical_verified"


SCHEMA_VERSION = "1.0"

# Secrets that must never appear in stored features.
_SECRET_KEY_PATTERNS = (
    "authorization",
    "cookie",
    "token",
    "api_key",
    "apikey",
    "password",
    "secret",
    "credential",
    "bearer",
)

# Patterns for text-level secret redaction (notes, free-text fields).
# Matches key=value and key: value forms.
_TEXT_SECRET_PATTERNS = [
    # Bearer token must come before authorization so "Bearer <token>" is
    # fully redacted rather than leaving the token after "Bearer" is eaten.
    re.compile(r"(bearer\s+)(\S+)", re.IGNORECASE),
    re.compile(r"(authorization\s*[:=]\s*(?:bearer\s+)?)(\S+)", re.IGNORECASE),
    re.compile(r"(cookie\s*[:=]\s*)(\S+)", re.IGNORECASE),
    re.compile(r"(set-cookie\s*[:=]\s*)(\S+)", re.IGNORECASE),
    re.compile(r"(api[_-]?key\s*[:=]\s*)(\S+)", re.IGNORECASE),
    re.compile(r"(access[_-]?token\s*[:=]\s*)(\S+)", re.IGNORECASE),
    re.compile(r"(refresh[_-]?token\s*[:=]\s*)(\S+)", re.IGNORECASE),
    re.compile(r"(token\s*[:=]\s*)(\S+)", re.IGNORECASE),
    re.compile(r"(passw(?:or)?d\s*[:=]\s*)(\S+)", re.IGNORECASE),
    re.compile(r"(secret\s*[:=]\s*)(\S+)", re.IGNORECASE),
    re.compile(r"(credential\s*[:=]\s*)(\S+)", re.IGNORECASE),
]

_MAX_NOTES_LEN = 2000

# ---------------------------------------------------------------------------
# Privacy hash key (per-install salt for HMAC).
# ---------------------------------------------------------------------------

_HASH_KEY: bytes | None = None
_HASH_KEY_PERSISTENT: bool = False


def _hash_key_path() -> Path:
    xdg = os.environ.get("XDG_DATA_HOME")
    base = Path(xdg) if xdg else (Path.home() / ".local" / "share")
    return base / "webscout" / "decision_hash.key"


def hash_key_persistent() -> bool:
    """Return True if the HMAC key is persisted to disk (not in-memory only)."""
    return _HASH_KEY_PERSISTENT


def _get_hash_key() -> bytes:
    """Return the per-install HMAC key.

    Priority:
      1. WEBSCOUT_DECISION_HASH_KEY env var (for tests / reproducible deploys)
      2. <data_dir>/webscout/decision_hash.key (atomically created 0600)
      3. In-memory random key (last resort; not persisted)

    Atomic creation uses os.open(O_WRONLY|O_CREAT|O_EXCL, 0o600) to avoid the
    write-then-chmod permission window. If another process creates the file
    concurrently, we read the existing key instead of overwriting it.
    """
    global _HASH_KEY, _HASH_KEY_PERSISTENT
    if _HASH_KEY is not None:
        return _HASH_KEY
    env_key = os.environ.get("WEBSCOUT_DECISION_HASH_KEY")
    if env_key:
        _HASH_KEY = env_key.encode("utf-8")
        _HASH_KEY_PERSISTENT = True  # env-provided key is stable across restarts
        return _HASH_KEY
    try:
        key_path = _hash_key_path()
        key_path.parent.mkdir(parents=True, exist_ok=True)
        if key_path.exists():
            _HASH_KEY = key_path.read_bytes().strip()
            _HASH_KEY_PERSISTENT = True
        else:
            new_key = os.urandom(32)
            try:
                # Atomic create with 0600 — no write-then-chmod window.
                fd = os.open(str(key_path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                try:
                    os.write(fd, new_key)
                finally:
                    os.close(fd)
                _HASH_KEY = new_key
                _HASH_KEY_PERSISTENT = True
            except FileExistsError:
                # Another process created it concurrently — read theirs.
                _HASH_KEY = key_path.read_bytes().strip()
                _HASH_KEY_PERSISTENT = True
    except OSError:
        _HASH_KEY = os.urandom(32)
        _HASH_KEY_PERSISTENT = False
    return _HASH_KEY


def _privacy_hash(value: str) -> str:
    """HMAC-SHA256 hex prefix (32 chars) using the per-install key.

    Same input -> same hash within one install. Different installs produce
    different hashes, preventing cross-install dictionary attacks.
    """
    key = _get_hash_key()
    return hmac.new(key, (value or "").encode("utf-8"), hashlib.sha256).hexdigest()[:32]


def canonical_url_hash(url: str) -> str:
    """HMAC-SHA256 hex of the normalized URL. Used as a stable identity
    without persisting the raw (possibly secret-bearing) URL."""
    normalized = (url or "").strip().lower()
    return _privacy_hash(normalized)


def sanitized_url_features(url: str) -> dict[str, Any]:
    """Return only scheme + host + privacy hash. Never the path/query/userinfo."""
    try:
        parsed = urlparse(url or "")
        return {
            "scheme": parsed.scheme or "",
            "host": (parsed.hostname or "").lower(),
            "canonical_hash": canonical_url_hash(url),
        }
    except Exception:
        return {"scheme": "", "host": "", "canonical_hash": canonical_url_hash(url)}


def query_hash(query: str) -> str:
    """HMAC-SHA256 hex prefix of a search query. Raw query is not stored."""
    return _privacy_hash(query or "")


def _scrub_dict(data: dict[str, Any]) -> dict[str, Any]:
    """Recursively remove keys that look like secrets, and stringify values
    that are not JSON-safe scalars."""
    clean: dict[str, Any] = {}
    for key, value in data.items():
        key_lower = str(key).lower()
        if any(p in key_lower for p in _SECRET_KEY_PATTERNS):
            continue
        if isinstance(value, dict):
            clean[key] = _scrub_dict(value)
        elif isinstance(value, (list, tuple)):
            clean[key] = [
                _scrub_dict(v) if isinstance(v, dict) else v
                for v in value
                if not (isinstance(v, dict) and any(p in str(k).lower() for p in _SECRET_KEY_PATTERNS for k in v))
            ]
        elif isinstance(value, (str, int, float, bool)) or value is None:
            clean[key] = value
        else:
            clean[key] = str(value)
    return clean


def _scrub_text(text: str, max_len: int = _MAX_NOTES_LEN) -> str:
    """Redact secret-like patterns from free-text fields (e.g. notes).

    Recognizes key=value and key: value forms for common secret names.
    Truncates to max_len to prevent unbounded storage.
    """
    if not text:
        return ""
    result = text
    for pattern in _TEXT_SECRET_PATTERNS:
        result = pattern.sub(lambda m: f"{m.group(1)}[REDACTED]", result)
    if len(result) > max_len:
        result = result[:max_len] + "...[truncated]"
    return result


@dataclass
class DecisionEvent:
    """One production decision event (fetch or search).

    All fields are sanitized scalars or hashes. The ``request_features`` and
    ``outcome_features`` dicts are scrubbed of secret-like keys at insert
    time by the store layer.
    """

    schema_version: str = SCHEMA_VERSION
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    trace_id: str = ""
    run_id: str = ""
    domain: DecisionDomain = DecisionDomain.FETCH
    stage: DecisionStage = DecisionStage.FINAL
    subject: str = ""  # provider / backend / action target name
    observed_status: str = ""  # e.g. success / empty / error / partial
    deterministic_reason: str = ""  # RecoveryReason or SearchRecoveryReason
    deterministic_action: str = ""  # RecoveryAction or SearchRecoveryAction
    production_action: str = ""  # what was actually executed
    production_outcome: str = ""  # e.g. accepted / browser_success / fallback_success / stopped
    started_at: float = field(default_factory=time.time)
    completed_at: float = field(default_factory=time.time)
    latency_ms: float = 0.0
    request_features: dict[str, Any] = field(default_factory=dict)
    outcome_features: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    jev_call_id: str = ""  # join key to Jev shadow record; empty if no Jev

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["domain"] = self.domain.value if isinstance(self.domain, DecisionDomain) else self.domain
        d["stage"] = self.stage.value if isinstance(self.stage, DecisionStage) else self.stage
        return d

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), default=str, ensure_ascii=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DecisionEvent:
        domain = data.get("domain", "fetch")
        stage = data.get("stage", "final")
        return cls(
            schema_version=data.get("schema_version", SCHEMA_VERSION),
            event_id=data.get("event_id", str(uuid.uuid4())),
            trace_id=data.get("trace_id", ""),
            run_id=data.get("run_id", ""),
            domain=DecisionDomain(domain) if domain in {e.value for e in DecisionDomain} else DecisionDomain.FETCH,
            stage=DecisionStage(stage) if stage in {e.value for e in DecisionStage} else DecisionStage.FINAL,
            subject=data.get("subject", ""),
            observed_status=data.get("observed_status", ""),
            deterministic_reason=data.get("deterministic_reason", ""),
            deterministic_action=data.get("deterministic_action", ""),
            production_action=data.get("production_action", ""),
            production_outcome=data.get("production_outcome", ""),
            started_at=float(data.get("started_at", 0)),
            completed_at=float(data.get("completed_at", 0)),
            latency_ms=float(data.get("latency_ms", 0)),
            request_features=dict(data.get("request_features", {})),
            outcome_features=dict(data.get("outcome_features", {})),
            metadata=dict(data.get("metadata", {})),
            jev_call_id=data.get("jev_call_id", ""),
        )
