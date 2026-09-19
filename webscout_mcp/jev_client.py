"""JevClient — TypeSafe semantic decision advisor abstraction (SHADOW ONLY).

This module defines the interface between WebScout's deterministic routing
layer and an external LLM-based semantic advisor ("Jev"). In this phase the
client is **shadow-only**: its decisions are recorded, never acted on.

No real TypeSafe API/SDK/credential is available in this environment yet.
We therefore ship:
  * ``JevClient`` (abstract interface)
  * ``JevDecision`` (typed result: yes/no + probability + confidence)
  * ``FakeJevClient`` (deterministic local heuristic; used in tests and as
    the default until a real TypeSafeJevClient is wired in)
  * ``NoopJevClient`` (returns None; used when JEV_ENABLED=false)

When official TypeSafe docs/SDK/credentials arrive, add a
``TypeSafeJevClient`` adapter behind the same interface — business code
must never import a third-party SDK directly.
"""

from __future__ import annotations

import hashlib
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Literal

from .logging_config import get_logger

log = get_logger(__name__)

JevQuestion = Literal["needs_escalation", "result_usable", "result_relevant"]


@dataclass
class JevDecision:
    """Typed result returned by Jev for one question.

    ``decision`` is the discrete yes/no call; ``probability_yes`` is the
    raw model score (0..1); ``confidence`` is how sure the model is that
    its probability is well-calibrated (0..1). In this phase neither
    value drives any production action.
    """

    question: JevQuestion
    decision: bool
    probability_yes: float
    confidence: float
    latency_ms: float
    provider: str = "fake"
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "question": self.question,
            "decision": self.decision,
            "probability_yes": round(self.probability_yes, 4),
            "confidence": round(self.confidence, 4),
            "latency_ms": round(self.latency_ms, 2),
            "provider": self.provider,
            "error": self.error,
        }


class JevClient(ABC):
    """Abstract advisor. Implementations must be safe to call from any path;
    they must never raise into the caller — wrap internal errors into
    JevDecision(error=...)."""

    name: str = "base"

    @abstractmethod
    async def ask(self, question: JevQuestion, state: dict[str, Any]) -> JevDecision:
        raise NotImplementedError

    async def aclose(self) -> None:  # pragma: no cover - optional
        return None


class NoopJevClient(JevClient):
    """Used when JEV_ENABLED=false. Returns no decision at all."""

    name = "noop"

    async def ask(self, question: JevQuestion, state: dict[str, Any]) -> JevDecision:
        return JevDecision(
            question=question,
            decision=False,
            probability_yes=0.0,
            confidence=0.0,
            latency_ms=0.0,
            provider="noop",
            error=None,
        )


class FakeJevClient(JevClient):
    """Deterministic local stand-in for TypeSafe Jev.

    This is NOT a real model. It applies simple, transparent heuristics on
    the already-sanitized state so shadow orchestration and persistence can
    be exercised end-to-end. When the real TypeSafe adapter lands, this
    client stays in the codebase only for unit tests.

    Heuristics (intentionally simple and explainable):
      * needs_escalation: leans yes when content is short and HTML-heavy.
      * result_usable: leans yes when extracted content is non-trivial.
      * result_relevant: leans yes when title+snippet are non-empty.
    """

    name = "fake"

    async def ask(self, question: JevQuestion, state: dict[str, Any]) -> JevDecision:
        start = time.time()
        try:
            if question == "needs_escalation":
                decision, prob, conf = self._needs_escalation(state)
            elif question == "result_usable":
                decision, prob, conf = self._result_usable(state)
            elif question == "result_relevant":
                decision, prob, conf = self._result_relevant(state)
            else:  # pragma: no cover - defensive
                decision, prob, conf = False, 0.0, 0.0
            return JevDecision(
                question=question,
                decision=decision,
                probability_yes=prob,
                confidence=conf,
                latency_ms=(time.time() - start) * 1000,
                provider=self.name,
            )
        except Exception as exc:  # pragma: no cover - defensive
            return JevDecision(
                question=question,
                decision=False,
                probability_yes=0.0,
                confidence=0.0,
                latency_ms=(time.time() - start) * 1000,
                provider=self.name,
                error=f"{type(exc).__name__}: {exc}",
            )

    @staticmethod
    def _needs_escalation(state: dict[str, Any]) -> tuple[bool, float, float]:
        length = int(state.get("content_length") or 0)
        status = int(state.get("http_status") or 0)
        if status == 403:
            return True, 0.9, 0.8
        if length < 500:
            return True, 0.7, 0.55
        if length < 2000:
            return False, 0.4, 0.5
        return False, 0.2, 0.6

    @staticmethod
    def _result_usable(state: dict[str, Any]) -> tuple[bool, float, float]:
        length = int(state.get("content_length") or 0)
        if length >= 1500:
            return True, 0.9, 0.8
        if length >= 300:
            return True, 0.6, 0.55
        return False, 0.2, 0.6

    @staticmethod
    def _result_relevant(state: dict[str, Any]) -> tuple[bool, float, float]:
        title = (state.get("title") or "").strip()
        snippet = (state.get("snippet") or "").strip()
        text = f"{title} {snippet}".lower()
        query = (state.get("query") or "").strip().lower()
        if not query:
            return False, 0.0, 0.0
        # Overlap heuristic: share >= 1 content word with query.
        qwords = {w for w in query.split() if len(w) > 2}
        if not qwords:
            return True, 0.5, 0.3
        overlap = sum(1 for w in qwords if w in text)
        prob = min(0.95, 0.3 + 0.25 * overlap)
        return overlap >= 1, prob, 0.5 + 0.1 * overlap


def make_jev_client(config: Any) -> JevClient:
    """Factory. Returns Noop when disabled; Fake when enabled but no real
    TypeSafe adapter is configured. When a real ``jev_base_url`` is set and
    a TypeSafe adapter is registered, it should be constructed here.

    Note: we deliberately do NOT fabricate a TypeSafeJevClient. Until we
    have official docs/SDK/credentials, enable=false is the safe default.
    """
    enabled = bool(getattr(config, "jev_enabled", False))
    if not enabled:
        return NoopJevClient()
    # Real TypeSafe adapter not wired yet. Use the local fake so shadow
    # orchestration can be exercised in staging, but this is never a real
    # model call.
    return FakeJevClient()


def stable_hash(*parts: str) -> str:
    """Short stable hash for trace ids / pseudo-ids (no PII)."""
    h = hashlib.sha1("|".join(parts).encode("utf-8"), usedforsecurity=False).hexdigest()[:12]
    return h
