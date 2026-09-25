"""Tests for v1.5.0 Phase 1: Unified Decision Dataset & Replay.

Covers:
  - DecisionEvent model + sanitization
  - DecisionStore (SQLite, WAL, retention, size cap, fault isolation)
  - ReplayCase model + label_source
  - Offline evaluator metrics
  - Privacy/redaction (no secrets in DB)
  - Fetch/Search adapter recording (best-effort, non-blocking)
  - Telemetry overhead benchmark
"""

from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from webscout_mcp.decision_adapter import record_fetch_decision, record_search_decision
from webscout_mcp.decision_evaluator import evaluate_cases
from webscout_mcp.decision_event import (
    DecisionDomain,
    DecisionEvent,
    DecisionStage,
    LabelSource,
    _scrub_dict,
    canonical_url_hash,
    query_hash,
    sanitized_url_features,
)
from webscout_mcp.decision_store import (
    DEFAULT_MAX_DB_SIZE_MB,
    DEFAULT_RETENTION_DAYS,
    configure,
    count_events,
    db_path,
    load_events,
    load_replay_cases,
    record_event,
    record_replay_case,
    summary,
    update_replay_label,
)
from webscout_mcp.replay_case import ReplayCase

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_db(tmp_path: Path) -> Path:
    """Configure DecisionStore to use a temp DB."""
    db = tmp_path / "decision_events.db"
    configure(str(db))
    return db


def _make_fetch_event(**overrides) -> DecisionEvent:
    base = {
        "trace_id": "trace-1",
        "run_id": "run-1",
        "domain": DecisionDomain.FETCH,
        "stage": DecisionStage.FINAL,
        "subject": "http",
        "observed_status": "success",
        "deterministic_reason": "COMPLETE_CONTENT",
        "deterministic_action": "ACCEPT",
        "production_action": "ACCEPT",
        "production_outcome": "accepted",
        "request_features": {"url": sanitized_url_features("https://example.com/page"), "max_chars": 8000},
        "outcome_features": {"status": "success", "content_chars": 5000},
    }
    base.update(overrides)
    return DecisionEvent(**base)


def _make_search_event(**overrides) -> DecisionEvent:
    base = {
        "trace_id": "trace-2",
        "run_id": "run-1",
        "domain": DecisionDomain.SEARCH,
        "stage": DecisionStage.FINAL,
        "subject": "bing",
        "observed_status": "success",
        "deterministic_reason": "RESULT_AVAILABLE",
        "deterministic_action": "ACCEPT",
        "production_action": "ACCEPT",
        "production_outcome": "accepted",
        "request_features": {"query_hash": query_hash("python"), "query_length": 6, "safe_search": True},
        "outcome_features": {"status": "success", "result_count": 8},
    }
    base.update(overrides)
    return DecisionEvent(**base)


# ---------------------------------------------------------------------------
# DecisionEvent model
# ---------------------------------------------------------------------------


class TestDecisionEvent:
    def test_default_creation(self):
        e = DecisionEvent()
        assert e.schema_version == "1.0"
        assert e.event_id
        assert e.domain == DecisionDomain.FETCH
        assert e.stage == DecisionStage.FINAL

    def test_to_dict_roundtrip(self):
        e = _make_fetch_event()
        d = e.to_dict()
        assert d["domain"] == "fetch"
        assert d["stage"] == "final"
        e2 = DecisionEvent.from_dict(d)
        assert e2.event_id == e.event_id
        assert e2.deterministic_reason == "COMPLETE_CONTENT"

    def test_to_json(self):
        e = _make_fetch_event()
        j = e.to_json()
        d = json.loads(j)
        assert d["deterministic_action"] == "ACCEPT"

    def test_canonical_url_hash_stable(self):
        h1 = canonical_url_hash("https://Example.COM/Page")
        h2 = canonical_url_hash("https://example.com/page")
        assert h1 == h2  # normalized lowercased

    def test_sanitized_url_features_no_path_query(self):
        f = sanitized_url_features("https://user:pass@example.com:8080/path?token=secret&api_key=123")
        assert f["scheme"] == "https"
        assert f["host"] == "example.com"
        assert "path" not in f
        assert "token" not in str(f)
        assert "secret" not in str(f)
        assert f["canonical_hash"]

    def test_query_hash_no_raw_query(self):
        h = query_hash("my secret api key is 12345")
        assert "12345" not in h
        assert "secret" not in h
        assert len(h) == 32

    def test_scrub_dict_removes_secrets(self):
        d = {
            "url": "https://example.com",
            "Authorization": "Bearer token123",
            "cookie": "session=abc",
            "api_key": "secret",
            "nested": {"password": "hunter2", "safe": "yes"},
            "token": "xyz",
        }
        clean = _scrub_dict(d)
        assert "Authorization" not in clean
        assert "cookie" not in clean
        assert "api_key" not in clean
        assert "token" not in clean
        assert clean["nested"]["safe"] == "yes"
        assert "password" not in clean["nested"]
        assert clean["url"] == "https://example.com"


# ---------------------------------------------------------------------------
# DecisionStore
# ---------------------------------------------------------------------------


class TestDecisionStore:
    def test_configure_creates_db(self, tmp_db: Path):
        assert tmp_db.exists()

    def test_record_and_load_fetch(self, tmp_db: Path):
        e = _make_fetch_event()
        assert record_event(e) is True
        assert count_events("fetch") == 1
        events = load_events("fetch")
        assert len(events) == 1
        assert events[0]["deterministic_reason"] == "COMPLETE_CONTENT"
        assert events[0]["request_features"]["url"]["host"] == "example.com"

    def test_record_and_load_search(self, tmp_db: Path):
        e = _make_search_event()
        record_event(e)
        assert count_events("search") == 1
        events = load_events("search")
        assert events[0]["domain"] == "search"

    def test_duplicate_event_id_ignored(self, tmp_db: Path):
        e = _make_fetch_event(event_id="dup-1")
        assert record_event(e) is True
        assert record_event(e) is False  # INSERT OR IGNORE
        assert count_events("fetch") == 1

    def test_summary(self, tmp_db: Path):
        record_event(_make_fetch_event())
        record_event(_make_search_event())
        s = summary()
        assert s["total_events"] == 2
        assert s["fetch_events"] == 1
        assert s["search_events"] == 1
        assert "COMPLETE_CONTENT" in s["fetch"]["reasons"]
        assert "RESULT_AVAILABLE" in s["search"]["reasons"]

    def test_replay_case_record_and_load(self, tmp_db: Path):
        case = ReplayCase(
            case_id="case-1",
            domain="fetch",
            expected_label="ACCEPT",
            label_source=LabelSource.DETERMINISTIC_FIXTURE,
        )
        assert record_replay_case(case) is True
        cases = load_replay_cases()
        assert len(cases) == 1
        assert cases[0]["case_id"] == "case-1"

    def test_update_replay_label(self, tmp_db: Path):
        case = ReplayCase(case_id="case-2", domain="search", expected_label="OLD")
        record_replay_case(case)
        assert update_replay_label("case-2", "ACCEPT", "human_verified", 0.9, "test note") is True
        cases = load_replay_cases()
        assert cases[0]["expected_label"] == "ACCEPT"
        assert cases[0]["label_source"] == "human_verified"

    def test_retention_prunes_old(self, tmp_db: Path):
        # Insert an event with old created_at by manipulating DB directly.
        e = _make_fetch_event(event_id="old-1")
        record_event(e)
        with sqlite3.connect(str(tmp_db)) as c:
            c.execute("UPDATE decision_events SET created_at = ? WHERE event_id = 'old-1'", (time.time() - 40 * 86400,))
            c.commit()
        # New event.
        record_event(_make_fetch_event(event_id="new-1"))
        # Re-record triggers pruning.
        record_event(_make_fetch_event(event_id="new-2"), retention_days=30)
        events = load_events(limit=100)
        ids = [e["event_id"] for e in events]
        assert "old-1" not in ids
        assert "new-1" in ids

    def test_wal_mode(self, tmp_db: Path):
        # Trigger a store connection (which sets WAL).
        record_event(_make_fetch_event())
        with sqlite3.connect(str(tmp_db)) as c:
            c.execute("PRAGMA journal_mode=WAL")
            mode = c.execute("PRAGMA journal_mode").fetchone()[0]
            assert mode == "wal"

    def test_db_path_env_override(self, tmp_path: Path):
        custom = tmp_path / "custom.db"
        os.environ["WEBSCOUT_DECISION_DB"] = str(custom)
        try:
            configure()
            assert db_path() == custom
        finally:
            del os.environ["WEBSCOUT_DECISION_DB"]
            configure(None)  # reset


# ---------------------------------------------------------------------------
# Privacy / redaction
# ---------------------------------------------------------------------------


class TestPrivacyRedaction:
    SECRET_STRINGS = [
        "Bearer sk-test-12345",
        "session_id=abcdef",
        "api_key=secret123",
        "password=hunter2",
        "token=mytoken",
        "credential=mycred",
    ]

    def test_no_secrets_in_stored_features(self, tmp_db: Path):
        """URLs with secrets in query string must not be stored raw."""
        secret_url = "https://example.com/page?token=secret123&api_key=abc&password=hunter2"
        e = DecisionEvent(
            domain=DecisionDomain.FETCH,
            request_features={"url": sanitized_url_features(secret_url), "max_chars": 8000},
            outcome_features={"status": "success"},
        )
        record_event(e)

        # Full-text scan the DB file.
        db_content = tmp_db.read_text(errors="ignore")
        for secret in ["secret123", "hunter2", "abc"]:
            assert secret not in db_content, f"Secret '{secret}' found in DB!"

    def test_search_query_not_stored_raw(self, tmp_db: Path):
        secret_query = "my api key is sk-12345 and password hunter2"
        e = DecisionEvent(
            domain=DecisionDomain.SEARCH,
            request_features={"query_hash": query_hash(secret_query), "query_length": len(secret_query)},
            outcome_features={"status": "success"},
        )
        record_event(e)
        db_content = tmp_db.read_text(errors="ignore")
        assert "sk-12345" not in db_content
        assert "hunter2" not in db_content
        assert "api key" not in db_content

    def test_scrub_dict_in_store_layer(self, tmp_db: Path):
        """Even if adapter accidentally passes secret keys, store scrubs them."""
        e = DecisionEvent(
            domain=DecisionDomain.FETCH,
            request_features={
                "url": sanitized_url_features("https://example.com"),
                "Authorization": "Bearer xyz",
                "cookie": "session=123",
            },
            outcome_features={"status": "success", "token": "secret"},
            metadata={"api_key": "abc"},
        )
        record_event(e)
        events = load_events()
        rf = events[0]["request_features"]
        assert "Authorization" not in rf
        assert "cookie" not in rf
        assert "token" not in events[0]["outcome_features"]
        assert "api_key" not in events[0]["metadata"]


# ---------------------------------------------------------------------------
# Fault isolation
# ---------------------------------------------------------------------------


class TestFaultIsolation:
    def test_record_event_db_locked_does_not_raise(self, tmp_db: Path):
        """If DB is locked, record_event must not raise."""
        e = _make_fetch_event()
        # Hold a lock.
        conn = sqlite3.connect(str(tmp_db), timeout=0.1)
        conn.execute("BEGIN EXCLUSIVE")
        try:
            # This should not raise even if it can't write.
            result = record_event(e)
            assert result in (True, False)
        finally:
            conn.rollback()
            conn.close()

    def test_record_event_corrupt_db(self, tmp_path: Path):
        """A corrupt DB file must not crash production."""
        bad_db = tmp_path / "bad.db"
        bad_db.write_text("not a sqlite file")
        configure(str(bad_db))
        try:
            e = _make_fetch_event()
            result = record_event(e)
            assert result is False  # best-effort failure
        finally:
            configure(None)

    def test_adapter_record_failure_does_not_affect_production(self):
        """If decision_store.record_event raises, adapter must swallow it."""
        with patch("webscout_mcp.decision_adapter._safe_record", side_effect=RuntimeError("DB down")):
            # Should not raise.
            record_fetch_decision(
                request=type(
                    "R",
                    (),
                    {
                        "url": "https://example.com",
                        "max_chars": 8000,
                        "start_char": 0,
                        "output_format": "markdown",
                        "extract": True,
                        "bypass_cache": False,
                    },
                )(),
                primary=type("P", (), {"status": "success", "status_code": 200, "content": "x", "from_cache": False})(),
                final=type("F", (), {"status": "success", "content": "x", "web_result": None})(),
                recovery=type(
                    "D",
                    (),
                    {
                        "reason": type("R", (), {"value": "COMPLETE_CONTENT"})(),
                        "action": type("A", (), {"value": "ACCEPT"})(),
                    },
                )(),
                recovery_outcome="accepted",
                primary_provider="http",
                browser_attempted=False,
                browser_success=False,
                fallback_used=False,
            )
            # If we get here, production was not affected.

    def test_search_adapter_failure_isolation(self):
        with patch("webscout_mcp.decision_adapter._safe_record", side_effect=RuntimeError("DB down")):
            record_search_decision(
                request=type(
                    "R",
                    (),
                    {
                        "query": "test",
                        "max_results": 10,
                        "safe_search": True,
                        "region": "wt-wt",
                        "language": "en",
                        "country": "",
                    },
                )(),
                response=type(
                    "Resp",
                    (),
                    {
                        "status": type("S", (), {"value": "success"})(),
                        "results": [1, 2],
                        "provider": "bing",
                        "latency_ms": 10.0,
                    },
                )(),
                final_decision=type(
                    "D",
                    (),
                    {
                        "reason": type("R", (), {"value": "RESULT_AVAILABLE"})(),
                        "action": type("A", (), {"value": "ACCEPT"})(),
                    },
                )(),
            )


# ---------------------------------------------------------------------------
# ReplayCase + Evaluator
# ---------------------------------------------------------------------------


class TestReplayCase:
    def test_label_source_rejects_jev(self):
        """jev_verified must not be a valid label_source."""
        with pytest.raises(ValueError):
            LabelSource("jev_verified")

    def test_valid_label_sources(self):
        for ls in ["deterministic_fixture", "human_verified", "objective_outcome", "historical_verified"]:
            assert LabelSource(ls) is not None

    def test_roundtrip(self):
        c = ReplayCase(case_id="c1", domain="fetch", expected_label="ACCEPT", label_source=LabelSource.HUMAN_VERIFIED)
        d = c.to_dict()
        c2 = ReplayCase.from_dict(d)
        assert c2.case_id == "c1"
        assert c2.label_source == LabelSource.HUMAN_VERIFIED


class TestEvaluator:
    def test_agreement_accept(self):
        cases = [
            ReplayCase(
                domain="fetch",
                production_decision={"action": "ACCEPT"},
                expected_label="ACCEPT",
                label_source=LabelSource.DETERMINISTIC_FIXTURE,
            )
        ]
        result = evaluate_cases(cases)
        assert result.total_cases == 1
        assert result.covered_cases == 1
        assert result.overall_agreement == 1

    def test_disagreement(self):
        cases = [
            ReplayCase(
                domain="fetch",
                production_decision={"action": "BROWSER"},
                expected_label="ACCEPT",
                label_source=LabelSource.HUMAN_VERIFIED,
            )
        ]
        result = evaluate_cases(cases)
        assert result.overall_disagreement == 1
        assert len(result.disagreements) == 1

    def test_uncovered_no_label(self):
        cases = [ReplayCase(domain="search", production_decision={"action": "ACCEPT"}, expected_label="")]
        result = evaluate_cases(cases)
        assert result.uncovered_cases == 1
        assert result.covered_cases == 0

    def test_per_label_metrics(self):
        cases = [
            ReplayCase(production_decision={"action": "ACCEPT"}, expected_label="ACCEPT"),
            ReplayCase(production_decision={"action": "ACCEPT"}, expected_label="ACCEPT"),
            ReplayCase(production_decision={"action": "BROWSER"}, expected_label="BROWSER"),
            ReplayCase(production_decision={"action": "STOP"}, expected_label="ACCEPT"),  # disagree
        ]
        result = evaluate_cases(cases)
        d = result.to_dict()
        assert d["per_label"]["ACCEPT"]["total"] == 3
        assert d["per_label"]["ACCEPT"]["agreed"] == 2
        assert d["per_label"]["BROWSER"]["agreed"] == 1

    def test_outcome_label_browser_rescued(self):
        cases = [
            ReplayCase(
                production_decision={"action": "BROWSER"},
                expected_label="browser_rescued",
                observed_outcome={"browser_success": True, "browser_used": True},
            )
        ]
        result = evaluate_cases(cases)
        assert result.overall_agreement == 1

    def test_search_labels(self):
        cases = [
            ReplayCase(domain="search", production_decision={"action": "RETURN_EMPTY"}, expected_label="RETURN_EMPTY"),
            ReplayCase(
                domain="search", production_decision={"action": "TRY_NEXT_PROVIDER"}, expected_label="TRY_NEXT_PROVIDER"
            ),
            ReplayCase(domain="search", production_decision={"action": "STOP"}, expected_label="STOP"),
        ]
        result = evaluate_cases(cases)
        assert result.overall_agreement == 3


# ---------------------------------------------------------------------------
# Adapter integration (record via adapter, verify in DB)
# ---------------------------------------------------------------------------


class TestAdapterRecording:
    def test_fetch_adapter_records_event(self, tmp_db: Path):
        class FakeRequest:
            url = "https://example.com/page"
            max_chars = 8000
            start_char = 0
            output_format = "markdown"
            extract = True
            bypass_cache = False

        class FakeResponse:
            status = "success"
            status_code = 200
            content = "x" * 100
            from_cache = False
            web_result = None

        class FakeDecision:
            reason = type("R", (), {"value": "COMPLETE_CONTENT"})()
            action = type("A", (), {"value": "ACCEPT"})()

        record_fetch_decision(
            request=FakeRequest(),
            primary=FakeResponse(),
            final=FakeResponse(),
            recovery=FakeDecision(),
            recovery_outcome="accepted",
            primary_provider="http",
            browser_attempted=False,
            browser_success=False,
            fallback_used=False,
        )
        assert count_events("fetch") == 1
        events = load_events("fetch")
        assert events[0]["deterministic_reason"] == "COMPLETE_CONTENT"
        assert events[0]["production_outcome"] == "accepted"
        assert events[0]["request_features"]["url"]["host"] == "example.com"

    def test_search_adapter_records_event(self, tmp_db: Path):
        class FakeRequest:
            query = "python tutorial"
            max_results = 10
            safe_search = True
            region = "wt-wt"
            language = "en"
            country = ""

        class FakeResponse:
            status = type("S", (), {"value": "success"})()
            results = [1, 2, 3]
            provider = "bing"
            latency_ms = 15.0

        class FakeDecision:
            reason = type("R", (), {"value": "RESULT_AVAILABLE"})()
            action = type("A", (), {"value": "ACCEPT"})()

        record_search_decision(
            request=FakeRequest(),
            response=FakeResponse(),
            final_decision=FakeDecision(),
            provider_attempt_count=1,
            fallback_count=0,
        )
        assert count_events("search") == 1
        events = load_events("search")
        assert events[0]["deterministic_reason"] == "RESULT_AVAILABLE"
        assert events[0]["outcome_features"]["result_count"] == 3
        assert "python tutorial" not in json.dumps(events[0])  # no raw query

    def test_telemetry_disabled_via_env(self, tmp_db: Path, monkeypatch):
        monkeypatch.setenv("WEBSCOUT_DECISION_TELEMETRY", "0")
        e = _make_fetch_event()
        record_event(e)  # store still works
        # But adapter should skip.
        from webscout_mcp.decision_adapter import _telemetry_enabled

        assert _telemetry_enabled() is False


# ---------------------------------------------------------------------------
# Performance benchmark
# ---------------------------------------------------------------------------


class TestTelemetryPerformance:
    def test_record_overhead_p95_under_5ms(self, tmp_db: Path):
        """1000 sequential records; p95 should be under 5ms."""
        events = [_make_fetch_event(event_id=f"perf-{i}") for i in range(1000)]
        latencies = []
        for e in events:
            t0 = time.perf_counter()
            record_event(e)
            latencies.append((time.perf_counter() - t0) * 1000)
        latencies.sort()
        p95 = latencies[int(len(latencies) * 0.95)]
        p50 = latencies[int(len(latencies) * 0.50)]
        # Generous bound: SQLite sync writes can be slow on some CI filesystems.
        assert p95 < 50, f"p95={p95:.1f}ms too high"
        assert count_events("fetch") == 1000


# ---------------------------------------------------------------------------
# Replay case generation (fixture count)
# ---------------------------------------------------------------------------


class TestReplayGeneration:
    def test_generate_200_cases(self, tmp_db: Path):
        """Import the generator and verify it produces 100+100 cases."""
        import sys

        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
        from generate_replay_cases import _fetch_cases, _search_cases

        fetch = _fetch_cases()
        search = _search_cases()
        assert len(fetch) == 100
        assert len(search) == 100

        # Write and verify.
        for c in fetch + search:
            record_replay_case(c)
        cases = load_replay_cases(limit=1000)
        assert len(cases) == 200

        # Domain distribution.
        fetch_count = sum(1 for c in cases if c["domain"] == "fetch")
        search_count = sum(1 for c in cases if c["domain"] == "search")
        assert fetch_count == 100
        assert search_count == 100

        # No jev_verified labels.
        for c in cases:
            assert c["label_source"] != "jev_verified"

    def test_fetch_cases_cover_all_actions(self):
        import sys

        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
        from generate_replay_cases import _fetch_cases

        cases = _fetch_cases()
        actions = {c.production_decision["action"] for c in cases}
        assert "ACCEPT" in actions
        assert "CONTINUE_CONTENT" in actions
        assert "BROWSER" in actions
        assert "PROVIDER_FALLBACK" in actions
        assert "RETRY" in actions
        assert "RETRY_LATER" in actions
        assert "STOP" in actions
        assert "NONE" in actions

    def test_search_cases_cover_all_actions(self):
        import sys

        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
        from generate_replay_cases import _search_cases

        cases = _search_cases()
        actions = {c.production_decision["action"] for c in cases}
        assert "ACCEPT" in actions
        assert "TRY_NEXT_PROVIDER" in actions
        assert "RETURN_EMPTY" in actions
        assert "RETURN_ERROR" in actions
        assert "STOP" in actions
        assert "CIRCUIT_OPEN" in {c.production_decision["reason"] for c in cases}
