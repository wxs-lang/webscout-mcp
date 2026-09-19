"""JevClient — TypeSafe semantic decision advisor abstraction (SHADOW ONLY).

This module defines the interface between WebScout's deterministic routing
layer and an external LLM-based semantic advisor ("Jev" via TypeSafe).
In this phase the client is **shadow-only**: its decisions are recorded,
never acted on.

Implementations:
  * ``JevClient`` (abstract interface)
  * ``JevDecision`` (typed result: yes/no + probability + confidence + usage)
  * ``NoopJevClient`` (used when JEV_ENABLED=false)
  * ``FakeJevClient`` (deterministic local heuristic; tests/dev only)
  * ``TypeSafeJevClient`` (real adapter around the official ``typesafe-sdk``)
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Literal

from .logging_config import get_logger

log = get_logger(__name__)

# Bump this when the English wording of any question changes. ShadowRecord
# stores it so old and new data remain comparable.
JEV_DECISION_SCHEMA_VERSION = "1"

JevQuestion = Literal["needs_escalation", "result_usable", "result_relevant"]

# Fixed English question instructions (versioned).
_JEV_INSTRUCTIONS: dict[str, str] = {
    "needs_escalation": (
        "Given this fetched page state, is the content insufficient for a general "
        "AI agent to use directly, such that browser escalation is warranted?"
    ),
    "result_usable": (
        "Does this fetched result contain enough genuine, useful page content for a "
        "general AI agent to consume directly?"
    ),
    "result_relevant": (
        "Given the user's search query and this search result, is this result "
        "meaningfully relevant enough to be worth fetching?"
    ),
}


@dataclass
class JevDecision:
    """Typed result returned by Jev for one question.

    ``decision`` is the discrete yes/no call; ``probability_yes`` is the
    raw model score (0..1); ``confidence`` is 0..1 when the SDK provides
    one, otherwise None. Neither value drives any production action.
    """

    question: JevQuestion
    decision: bool
    probability_yes: float
    confidence: float | None
    latency_ms: float
    provider: str = "fake"
    error: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "question": self.question,
            "decision": self.decision,
            "probability_yes": round(self.probability_yes, 4),
            "confidence": round(self.confidence, 4) if self.confidence is not None else None,
            "latency_ms": round(self.latency_ms, 2),
            "provider": self.provider,
            "error": self.error,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
        }


class JevClient(ABC):
    """Abstract advisor. Implementations must be safe to call from any path;
    they must never raise into the caller — wrap internal errors into
    JevDecision(error=...)."""

    name: str = "base"

    @abstractmethod
    async def ask_many(self, questions: list[JevQuestion], state: dict[str, Any]) -> dict[JevQuestion, JevDecision]:
        """Batch: one network call for several questions on the same state."""
        raise NotImplementedError

    async def ask(self, question: JevQuestion, state: dict[str, Any]) -> JevDecision:
        results = await self.ask_many([question], state)
        return results[question]

    async def aclose(self) -> None:  # pragma: no cover - optional
        return None


class NoopJevClient(JevClient):
    name = "noop"

    async def ask_many(self, questions: list[JevQuestion], state: dict[str, Any]) -> dict[JevQuestion, JevDecision]:
        return {
            q: JevDecision(
                question=q,
                decision=False,
                probability_yes=0.0,
                confidence=None,
                latency_ms=0.0,
                provider="noop",
            )
            for q in questions
        }


class FakeJevClient(JevClient):
    """Deterministic local stand-in. Used only for unit tests / local dev.

    Never used in production unless JEV_PROVIDER=fake is explicit.
    """

    name = "fake"

    async def ask_many(self, questions: list[JevQuestion], state: dict[str, Any]) -> dict[JevQuestion, JevDecision]:
        start = time.time()
        out: dict[JevQuestion, JevDecision] = {}
        for q in questions:
            try:
                if q == "needs_escalation":
                    d, p, c = self._needs_escalation(state)
                elif q == "result_usable":
                    d, p, c = self._result_usable(state)
                else:
                    d, p, c = self._result_relevant(state)
                out[q] = JevDecision(
                    question=q,
                    decision=d,
                    probability_yes=p,
                    confidence=c,
                    latency_ms=(time.time() - start) * 1000,
                    provider="fake",
                )
            except Exception as exc:  # pragma: no cover
                out[q] = JevDecision(
                    question=q,
                    decision=False,
                    probability_yes=0.0,
                    confidence=None,
                    latency_ms=(time.time() - start) * 1000,
                    provider="fake",
                    error=f"{type(exc).__name__}: {exc}",
                )
        return out

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
        qwords = {w for w in query.split() if len(w) > 2}
        if not qwords:
            return True, 0.5, 0.3
        overlap = sum(1 for w in qwords if w in text)
        prob = min(0.95, 0.3 + 0.25 * overlap)
        return overlap >= 1, prob, 0.5 + 0.1 * overlap


class TypeSafeJevClient(JevClient):
    """Real adapter around the official ``typesafe-sdk`` (0.6.x).

    Uses the async client. All network calls are wrapped in
    ``asyncio.wait_for`` with the configured timeout. The SDK client is
    reused across requests (one per process) and closed via ``aclose()``.
    """

    name = "typesafe"

    def __init__(
        self,
        api_key: str,
        *,
        model: str = "jev-latest",
        timeout_ms: int = 1000,
        base_url: str = "",
    ) -> None:
        if not api_key:
            raise ValueError("TypeSafeJevClient requires a non-empty api_key")
        self.model = model
        self.timeout_s = float(timeout_ms) / 1000.0
        self._client = None
        self._api_key = api_key
        self._base_url = base_url

    def _ensure_client(self):
        if self._client is None:
            from typesafe_sdk import AsyncTypeSafeClient

            kwargs: dict[str, Any] = {"api_key": self._api_key}
            if self._base_url:
                kwargs["base_url"] = self._base_url
            self._client = AsyncTypeSafeClient(**kwargs)
        return self._client

    async def ask_many(self, questions: list[JevQuestion], state: dict[str, Any]) -> dict[JevQuestion, JevDecision]:
        from typesafe_sdk import Noul

        start = time.time()
        result: dict[JevQuestion, JevDecision] = {}
        try:
            client = self._ensure_client()
            qmap: dict[str, Any] = {q: Noul(instructions=_JEV_INSTRUCTIONS[q]) for q in questions}
            resp = await asyncio.wait_for(
                client.system_one(
                    state=state,
                    questions=qmap,
                    model=self.model,
                    timeout=self.timeout_s,
                ),
                timeout=self.timeout_s + 0.5,
            )
            usage = getattr(resp, "usage", None)
            in_tok = getattr(usage, "input_tokens", None) if usage else None
            out_tok = getattr(usage, "output_tokens", None) if usage else None
            latency_ms = (time.time() - start) * 1000
            for q in questions:
                ans = resp.answers.get(q)
                if ans is None:
                    result[q] = JevDecision(
                        question=q,
                        decision=False,
                        probability_yes=0.0,
                        confidence=None,
                        latency_ms=latency_ms,
                        provider=self.name,
                        error="missing_answer",
                    )
                    continue
                noul = float(getattr(ans, "noul", 0.0))
                noul = max(0.0, min(1.0, noul))
                result[q] = JevDecision(
                    question=q,
                    decision=noul >= 0.5,
                    probability_yes=noul,
                    confidence=None,  # SDK 0.6.x does not expose confidence
                    latency_ms=latency_ms,
                    provider=self.name,
                    input_tokens=in_tok,
                    output_tokens=out_tok,
                )
        except asyncio.TimeoutError:
            for q in questions:
                result[q] = JevDecision(
                    question=q,
                    decision=False,
                    probability_yes=0.0,
                    confidence=None,
                    latency_ms=(time.time() - start) * 1000,
                    provider=self.name,
                    error="timeout",
                )
        except Exception as exc:
            safe = _sanitize_error(exc, self._api_key)
            for q in questions:
                result[q] = JevDecision(
                    question=q,
                    decision=False,
                    probability_yes=0.0,
                    confidence=None,
                    latency_ms=(time.time() - start) * 1000,
                    provider=self.name,
                    error=safe,
                )
        return result

    async def aclose(self) -> None:
        if self._client is not None:
            try:
                await self._client.aclose()
            except Exception:  # pragma: no cover
                log.debug("TypeSafe client close failed", exc_info=True)
            finally:
                self._client = None


def _sanitize_error(exc: Exception, api_key: str) -> str:
    """Strip any potential credential leakage from an exception message."""
    msg = f"{type(exc).__name__}: {exc}"
    if api_key and api_key in msg:
        msg = msg.replace(api_key, "<redacted>")
    return msg[:200]


def make_jev_client(config: Any) -> JevClient:
    """Factory. Respects JEV_ENABLED and JEV_PROVIDER.

    Rules:
      * disabled -> NoopJevClient
      * provider=fake -> FakeJevClient (tests/dev only)
      * provider=typesafe + key -> TypeSafeJevClient
      * provider=typesafe + no key -> NoopJevClient + warning (no silent fake fallback)
    """
    enabled = bool(getattr(config, "jev_enabled", False))
    if not enabled:
        return NoopJevClient()

    provider = (getattr(config, "jev_provider", "typesafe") or "typesafe").lower()
    if provider == "fake":
        log.warning("JEV_PROVIDER=fake: using local heuristic client (tests/dev only)")
        return FakeJevClient()
    if provider == "noop":
        return NoopJevClient()

    # Default: typesafe
    api_key = os.environ.get("TYPESAFE_API_KEY") or getattr(config, "jev_api_key", "") or ""
    if not api_key:
        log.warning(
            "JEV_PROVIDER=typesafe but TYPESAFE_API_KEY is not set; Jev shadow is disabled (no silent fake fallback)."
        )
        return NoopJevClient()
    try:
        return TypeSafeJevClient(
            api_key=api_key,
            model=getattr(config, "jev_model", "jev-latest"),
            timeout_ms=int(getattr(config, "jev_timeout_ms", 1000)),
            base_url=getattr(config, "jev_base_url", "") or "",
        )
    except Exception:  # pragma: no cover
        log.exception("TypeSafeJevClient init failed; shadow disabled")
        return NoopJevClient()


def stable_hash(*parts: str) -> str:
    """Short stable hash for trace ids / pseudo-ids (no PII)."""
    h = hashlib.sha1("|".join(parts).encode("utf-8"), usedforsecurity=False).hexdigest()[:12]
    return h
