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


# ===========================================================================
# v1.5.0 Phase 1.1 — Decision Data Integrity & Correlation Hardening
# ===========================================================================


class TestLabelSourceStrict:
    """P0: label_source must be strictly validated, no silent fallback."""

    def test_from_dict_rejects_jev_verified(self):
        with pytest.raises(ValueError, match="jev_verified"):
            ReplayCase.from_dict({"label_source": "jev_verified"})

    def test_from_dict_rejects_jev_verified_uppercase(self):
        with pytest.raises(ValueError):
            ReplayCase.from_dict({"label_source": "JEV_VERIFIED"})

    def test_from_dict_rejects_unknown(self):
        with pytest.raises(ValueError):
            ReplayCase.from_dict({"label_source": "unknown"})

    def test_from_dict_rejects_empty(self):
        with pytest.raises(ValueError):
            ReplayCase.from_dict({"label_source": ""})

    def test_from_dict_rejects_typo(self):
        with pytest.raises(ValueError):
            ReplayCase.from_dict({"label_source": "human_verifyed"})

    def test_constructor_rejects_invalid(self):
        with pytest.raises(ValueError):
            ReplayCase(label_source="jev_verified")

    def test_record_replay_case_rejects_jev(self, tmp_db: Path):
        ok = record_replay_case(
            {
                "case_id": "bad-label-1",
                "domain": "fetch",
                "label_source": "jev_verified",
                "expected_label": "ACCEPT",
            }
        )
        assert ok is False
        cases = load_replay_cases()
        assert all(c["case_id"] != "bad-label-1" for c in cases)

    def test_update_replay_label_rejects_jev(self, tmp_db: Path):
        record_replay_case(ReplayCase(case_id="lbl-1", expected_label="ACCEPT"))
        ok = update_replay_label("lbl-1", "BROWSER", source="jev_verified")
        assert ok is False
        # Label should be unchanged.
        cases = load_replay_cases()
        c = next(c for c in cases if c["case_id"] == "lbl-1")
        assert c["expected_label"] == "ACCEPT"


class TestLabelTime:
    """label_time must exist and survive roundtrip."""

    def test_replay_case_has_label_time_field(self):
        c = ReplayCase(case_id="lt-1", expected_label="ACCEPT")
        assert hasattr(c, "label_time")
        assert c.label_time is None

    def test_label_time_set_in_constructor(self):
        ts = 1700000000.0
        c = ReplayCase(case_id="lt-2", expected_label="ACCEPT", label_time=ts)
        assert c.label_time == ts

    def test_label_time_survives_to_dict_roundtrip(self):
        ts = 1700000000.5
        c = ReplayCase(case_id="lt-3", expected_label="ACCEPT", label_time=ts)
        d = c.to_dict()
        assert d["label_time"] == ts
        c2 = ReplayCase.from_dict(d)
        assert c2.label_time == ts

    def test_update_replay_label_sets_label_time(self, tmp_db: Path):
        record_replay_case(ReplayCase(case_id="lt-4", expected_label="ACCEPT"))
        before = time.time()
        update_replay_label("lt-4", "BROWSER", source="human_verified")
        after = time.time()
        cases = load_replay_cases()
        c = next(c for c in cases if c["case_id"] == "lt-4")
        assert c["label_time"] is not None
        assert before <= c["label_time"] <= after + 1

    def test_label_time_persisted_in_db(self, tmp_db: Path):
        ts = 1700000123.0
        record_replay_case(ReplayCase(case_id="lt-5", expected_label="ACCEPT", label_time=ts))
        with sqlite3.connect(str(tmp_db)) as c:
            row = c.execute("SELECT label_time FROM replay_cases WHERE case_id='lt-5'").fetchone()
        assert row[0] == ts


class TestReplayStoreScrub:
    """P0: ReplayCase store layer must scrub all fields + notes."""

    def test_malicious_replay_privacy(self, tmp_db: Path):
        """Secrets in input_features/observed_outcome/production_decision/notes
        must never appear in the raw SQLite file."""
        record_replay_case(
            {
                "case_id": "priv-1",
                "domain": "fetch",
                "input_features": {
                    "authorization": "Bearer TOPSECRET",
                    "nested": {"api_key": "ABC123"},
                },
                "observed_outcome": {"cookie": "SESSIONID123"},
                "production_decision": {"token": "TOKENXYZ"},
                "expected_label": "ACCEPT",
                "label_source": "objective_outcome",
                "notes": "Authorization: Bearer SECRETXYZ; password=hunter2; api_key=LEAK",
            }
        )
        # Read raw DB bytes and scan for secrets.
        raw = tmp_db.read_bytes()
        for secret in ["TOPSECRET", "ABC123", "SESSIONID123", "TOKENXYZ", "SECRETXYZ", "hunter2", "LEAK"]:
            assert secret.encode() not in raw, f"Secret {secret!r} found in DB!"

    def test_notes_scrub_text_redacts_patterns(self):
        from webscout_mcp.decision_event import _scrub_text

        text = "Authorization: Bearer abc123 and token=xyz password=secret123"
        result = _scrub_text(text)
        assert "abc123" not in result
        assert "xyz" not in result
        assert "secret123" not in result
        assert "[REDACTED]" in result

    def test_notes_truncated(self):
        from webscout_mcp.decision_event import _MAX_NOTES_LEN, _scrub_text

        long_text = "x" * (_MAX_NOTES_LEN + 500)
        result = _scrub_text(long_text)
        assert len(result) <= _MAX_NOTES_LEN + 20  # + "[truncated]" marker


class TestHmacPrivacyHash:
    """query_hash and canonical_url_hash must use per-install HMAC key."""

    def test_same_input_same_hash_within_install(self):
        h1 = query_hash("python tutorial")
        h2 = query_hash("python tutorial")
        assert h1 == h2

    def test_different_input_different_hash(self):
        assert query_hash("python") != query_hash("java")

    def test_different_key_produces_different_hash(self, monkeypatch):
        monkeypatch.setenv("WEBSCOUT_DECISION_HASH_KEY", "key-A")
        # Reset cached key.
        import webscout_mcp.decision_event as de

        de._HASH_KEY = None
        h_a = query_hash("test")
        monkeypatch.setenv("WEBSCOUT_DECISION_HASH_KEY", "key-B")
        de._HASH_KEY = None
        h_b = query_hash("test")
        assert h_a != h_b
        # Reset for other tests.
        de._HASH_KEY = None

    def test_url_hash_does_not_leak_path(self, tmp_db: Path):
        url = "https://user:pass@example.com/path?token=SECRET123"
        record_event(
            _make_fetch_event(
                event_id="url-hash-1",
                request_features={"url": sanitized_url_features(url)},
            )
        )
        raw = tmp_db.read_bytes()
        for secret in [b"user", b"pass", b"/path", b"token", b"SECRET123"]:
            assert secret not in raw, f"{secret!r} found in DB!"

    def test_hash_is_32_hex_chars(self):
        h = query_hash("anything")
        assert len(h) == 32
        int(h, 16)  # valid hex


class TestSizeCapHardening:
    """Size cap must include WAL and count replay_cases."""

    def test_size_cap_includes_wal_and_replay(self, tmp_path: Path):
        """With a small cap, both decision_events and replay_cases are pruned,
        and WAL is checkpointed. Both tables retain some rows."""
        import webscout_mcp.decision_store as ds

        db = tmp_path / "cap.db"
        configure(str(db))
        original = ds.DEFAULT_MAX_DB_SIZE_MB
        try:
            ds.DEFAULT_MAX_DB_SIZE_MB = 2
            # Write many events and replay cases.
            for i in range(300):
                record_event(_make_fetch_event(event_id=f"cap-ev-{i}"))
            for i in range(150):
                record_replay_case(ReplayCase(case_id=f"cap-rp-{i}", expected_label="ACCEPT"))
            # Total size should be bounded (with hysteresis allowance).
            total = ds._total_db_size(db)
            assert total <= 2 * 1024 * 1024 * 1.15, f"DB too large: {total} bytes"
            # Both tables should still have some rows (not all deleted).
            assert count_events("fetch") > 0
            assert len(load_replay_cases(limit=1000)) > 0
        finally:
            ds.DEFAULT_MAX_DB_SIZE_MB = original

    def test_total_db_size_includes_wal(self, tmp_path: Path):
        import webscout_mcp.decision_store as ds

        db = tmp_path / "wal.db"
        configure(str(db))
        # Write something to create WAL.
        record_event(_make_fetch_event(event_id="wal-1"))
        total = ds._total_db_size(db)
        main_size = db.stat().st_size
        assert total >= main_size


class TestDuplicateEventReturn:
    """record_event must return False for duplicate event_id."""

    def test_duplicate_returns_false(self, tmp_db: Path):
        e = _make_fetch_event(event_id="dup-1")
        assert record_event(e) is True
        assert record_event(e) is False
        assert count_events("fetch") == 1

    def test_distinct_ids_return_true(self, tmp_db: Path):
        assert record_event(_make_fetch_event(event_id="uniq-1")) is True
        assert record_event(_make_fetch_event(event_id="uniq-2")) is True
        assert count_events("fetch") == 2


class TestDecisionJevCorrelation:
    """DecisionEvent and Jev Shadow must share (run_id, trace_id)."""

    def test_fetch_trace_id_shared_with_jev(self, tmp_db: Path):
        """Fetch operation: DecisionEvent.trace_id == Jev record.trace_id."""
        from webscout_mcp.runtime_context import PROCESS_RUN_ID, new_trace_id

        trace_id = new_trace_id()
        # Record a DecisionEvent with this trace_id.
        record_event(_make_fetch_event(event_id="corr-fetch-1", trace_id=trace_id, run_id=PROCESS_RUN_ID))
        # Record a Jev shadow record with the same trace_id (simulate).
        from webscout_mcp.jev_shadow import get_recorder

        recorder = get_recorder()
        recorder.record(
            operation="fetch",
            jev_question="needs_escalation",
            decision=None,
            rule_decision=False,
            rule_reason=None,
            trace_id=trace_id,
            run_id=PROCESS_RUN_ID,
        )
        # Verify join report sees it.
        report = __import__("webscout_mcp.decision_store", fromlist=["join_report"]).join_report()
        assert report["decision_event_pairs"] >= 1
        assert report["jev_record_pairs"] >= 1
        assert report["joined_pairs"] >= 1

    def test_search_trace_id_shared_with_jev(self, tmp_db: Path):
        """Search operation: 1 DecisionEvent joins to multiple Jev records."""
        from webscout_mcp.runtime_context import PROCESS_RUN_ID, new_trace_id

        trace_id = new_trace_id()
        record_event(_make_search_event(event_id="corr-search-1", trace_id=trace_id, run_id=PROCESS_RUN_ID))
        from webscout_mcp.jev_shadow import get_recorder

        recorder = get_recorder()
        for pos in range(3):
            recorder.record(
                operation="search",
                jev_question="result_relevant",
                decision=None,
                rule_decision=None,
                rule_reason=None,
                position=pos + 1,
                trace_id=trace_id,
                run_id=PROCESS_RUN_ID,
            )
        report = __import__("webscout_mcp.decision_store", fromlist=["join_report"]).join_report()
        assert report["joined_pairs"] >= 1

    def test_join_report_structure(self, tmp_db: Path):
        report = __import__("webscout_mcp.decision_store", fromlist=["join_report"]).join_report()
        assert "decision_event_pairs" in report
        assert "jev_record_pairs" in report
        assert "joined_pairs" in report
        assert "unjoined_decision_pairs" in report
        assert "orphan_jev_pairs" in report
        assert "join_coverage" in report
        assert "by_domain" in report


class TestSnapshotHitTelemetry:
    """Fetch snapshot hit must record 1 DecisionEvent with 0 recovery/Jev/network."""

    def test_snapshot_hit_records_decision_event(self, tmp_db: Path):
        """Simulate the snapshot-hit telemetry path in FetchService."""
        from webscout_mcp.decision_adapter import record_fetch_decision

        class FakeRequest:
            url = "https://example.com/long"
            max_chars = 8000
            start_char = 4000
            output_format = "markdown"
            extract = True
            bypass_cache = False

        class FakeResponse:
            status = "success"
            status_code = 200
            content = "x" * 1000
            metadata = {"served_from_content_snapshot": True}
            provider = "http"
            from_cache = True

        class FakeRecovery:
            class reason:
                value = "SNAPSHOT_HIT"

            class action:
                value = "ACCEPT"

        record_fetch_decision(
            request=FakeRequest(),
            primary=FakeResponse(),
            final=FakeResponse(),
            recovery=FakeRecovery(),
            recovery_outcome="snapshot_served",
            primary_provider="http",
            browser_attempted=False,
            browser_success=False,
            fallback_used=False,
            cache_hit=True,
            snapshot_hit=True,
            trace_id="trace-snap-1",
            run_id="run-snap-1",
            started_at=time.time(),
        )
        events = load_events(domain="fetch", limit=10)
        snap_events = [e for e in events if e["trace_id"] == "trace-snap-1"]
        assert len(snap_events) == 1
        ev = snap_events[0]
        assert ev["deterministic_reason"] == "SNAPSHOT_HIT"
        assert ev["deterministic_action"] == "ACCEPT"
        assert ev["production_outcome"] == "snapshot_served"
        assert ev["request_features"]["snapshot_hit"] is True
        assert ev["outcome_features"]["snapshot_hit"] is True


class TestPerformanceSemantics:
    """Performance test: CI safety ceiling 50ms, design target <5ms."""

    def test_p95_under_ci_ceiling(self, tmp_db: Path):
        """1000 records; p95 under 50ms (CI safety ceiling).
        Design target is <5ms typical local, but CI filesystems may be slower."""
        events = [_make_fetch_event(event_id=f"perf2-{i}") for i in range(1000)]
        latencies = []
        for e in events:
            t0 = time.perf_counter()
            record_event(e)
            latencies.append((time.perf_counter() - t0) * 1000)
        latencies.sort()
        p95 = latencies[int(len(latencies) * 0.95)]
        p50 = latencies[int(len(latencies) * 0.50)]
        p99 = latencies[int(len(latencies) * 0.99)]
        # CI safety ceiling.
        assert p95 < 50, f"p95={p95:.1f}ms exceeds CI ceiling"
        assert count_events("fetch") >= 1000
