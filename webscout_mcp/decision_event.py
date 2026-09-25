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
import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum
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


def canonical_url_hash(url: str) -> str:
    """SHA-256 hex of the full normalized URL. Used as a stable identity
    without persisting the raw (possibly secret-bearing) URL."""
    normalized = (url or "").strip().lower()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:32]


def sanitized_url_features(url: str) -> dict[str, Any]:
    """Return only scheme + host + canonical hash. Never the path/query."""
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
    """SHA-256 hex prefix of a search query. Raw query is not stored by
    default; use opt-in debug mode to persist it."""
    return hashlib.sha256((query or "").encode("utf-8")).hexdigest()[:32]


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
