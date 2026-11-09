"""Phase 2.1 run-isolation tests (hermetic, offline).

Covers:
  a. run-scoped join_report (run-A joined / run-B unexpected-unjoined; no
     cross-run pollution; global report aggregates).
  b. ReplayCase migration: old DB (no run_id/trace_id) upgrades keeping rows;
     fresh DB has both columns + idx_replay_run / idx_replay_trace.
  c. Replay<->Jev join keys on (run_id, trace_id) — case_id is NEVER a trace.
  d. materialize_objective_replay_cases: deterministic case_ids, correct
     run/trace/label, idempotent re-runs.
  e. SEARCH_SUCCESS / result_count>0 never creates a semantic case.
  f. load_replay_cases(run_id=...) scoping.
  g. set_process_run_id_for_evaluation patches env + module globals + the
     already-imported bound PROCESS_RUN_ID in fetch/search/jev_shadow.
"""

from __future__ import annotations

import os
import sqlite3
import time
import uuid
from pathlib import Path

import pytest

from webscout_mcp import decision_store, jev_store, runtime_context
from webscout_mcp.advisor_evaluator import build_labeled_rows
from webscout_mcp.decision_event import DecisionDomain, DecisionEvent, DecisionStage
from webscout_mcp.objective_labeler import materialize_objective_replay_cases
from webscout_mcp.replay_case import ReplayCase

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def hermetic_stores(tmp_path: Path):
    """Isolate decision + jev stores into tmp DBs; restore defaults afterwards."""
    decision_db = tmp_path / "decision_events.db"
    jev_db = tmp_path / "jev_shadow.db"
    decision_store.configure(str(decision_db))
    jev_store.configure(str(jev_db))
    try:
        yield decision_db, jev_db
    finally:
        decision_store.configure(None)
        jev_store.configure(None)


def _make_event(
    run_id: str,
    trace_id: str,
    *,
    event_id: str | None = None,
    domain: str = "fetch",
    eligible: bool = True,
    enabled: bool = True,
    outcome: dict | None = None,
) -> DecisionEvent:
    return DecisionEvent(
        event_id=event_id or f"ev-{run_id}-{trace_id}",
        run_id=run_id,
        trace_id=trace_id,
        domain=DecisionDomain(domain),
        stage=DecisionStage.FINAL,
        subject="http",
        observed_status="success",
        deterministic_reason="COMPLETE_CONTENT",
        deterministic_action="ACCEPT",
        production_action="ACCEPT",
        production_outcome="accepted",
        request_features={"scheme": "https", "host": "example.com"},
        outcome_features=outcome or {"status": "success", "content_chars": 5000, "final_extraction_success": True},
        metadata={"jev_eligible": eligible, "jev_enabled": enabled},
    )


def _insert_jev(run_id: str, trace_id: str, *, operation: str = "fetch", question: str = "needs_escalation") -> None:
    with sqlite3.connect(str(jev_store.db_path())) as c:
        c.execute(
            "INSERT INTO jev_records (timestamp, run_id, trace_id, operation, jev_question) VALUES (?, ?, ?, ?, ?)",
            (time.time(), run_id, trace_id, operation, question),
        )
        c.commit()


# ---------------------------------------------------------------------------
# a. run isolation of join_report
# ---------------------------------------------------------------------------


class TestRunScopedJoinReport:
    def test_run_a_joined_run_b_unexpected(self, hermetic_stores):
        decision_store.record_event(_make_event("run-A", "t-a", event_id="ev-a1"))
        _insert_jev("run-A", "t-a", question="needs_escalation")
        # run-B: eligible+enabled but NO jev row.
        decision_store.record_event(_make_event("run-B", "t-b", event_id="ev-b1"))

        rep_a = decision_store.join_report("run-A")
        assert rep_a["advisor_enabled_decisions"] == 1
        assert rep_a["joined_enabled_eligible"] == 1
        assert rep_a["join_coverage"] == 1.0
        assert rep_a["unexpected_unjoined"] == 0

        rep_b = decision_store.join_report("run-B")
        assert rep_b["advisor_enabled_decisions"] == 1
        assert rep_b["join_coverage"] == 0.0
        assert rep_b["unexpected_unjoined"] == 1

        # Global report aggregates both; runs do not pollute each other.
        rep_all = decision_store.join_report()
        assert rep_all["total_decisions"] == 2
        assert rep_all["advisor_enabled_decisions"] == 2
        assert rep_all["joined_enabled_eligible"] == 1
        assert rep_all["unexpected_unjoined"] == 1
        assert rep_all["by_domain"]["fetch"]["decision_events"] == 2
        assert rep_all["by_domain"]["fetch"]["advisor_enabled_decisions"] == 2

    def test_scoped_by_domain_only_see_run(self, hermetic_stores):
        decision_store.record_event(_make_event("run-A", "t-a"))
        decision_store.record_event(_make_event("run-B", "t-b"))
        rep = decision_store.join_report("run-A")
        assert rep["by_domain"]["fetch"]["decision_events"] == 1


# ---------------------------------------------------------------------------
# b. ReplayCase migration
# ---------------------------------------------------------------------------


class TestReplayCaseMigration:
    def test_old_db_upgrades_keeping_rows(self, tmp_path: Path):
        old_db = tmp_path / "old_decision_events.db"
        # Hand-built v1 schema: replay_cases WITHOUT run_id/trace_id.
        with sqlite3.connect(str(old_db)) as c:
            c.executescript(
                """
                CREATE TABLE decision_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    schema_version TEXT NOT NULL, event_id TEXT NOT NULL UNIQUE,
                    trace_id TEXT, run_id TEXT, domain TEXT NOT NULL,
                    stage TEXT NOT NULL, subject TEXT, observed_status TEXT,
                    deterministic_reason TEXT, deterministic_action TEXT,
                    production_action TEXT, production_outcome TEXT,
                    started_at REAL, completed_at REAL, latency_ms REAL,
                    request_features TEXT, outcome_features TEXT, metadata TEXT,
                    jev_call_id TEXT, created_at REAL NOT NULL
                );
                CREATE TABLE replay_cases (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    case_id TEXT NOT NULL UNIQUE, domain TEXT NOT NULL,
                    input_features TEXT, observed_outcome TEXT,
                    production_decision TEXT, expected_label TEXT,
                    label_source TEXT, label_confidence REAL, label_time REAL,
                    notes TEXT, created_at REAL NOT NULL
                );
                """
            )
            c.execute(
                "INSERT INTO replay_cases (case_id, domain, expected_label, label_source, "
                "label_confidence, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                ("legacy-1", "fetch", "semantic/needs_more_content", "human_verified", 0.9, time.time()),
            )
            c.commit()

        decision_store.configure(str(old_db))
        try:
            cases = decision_store.load_replay_cases()
            assert len(cases) == 1
            assert cases[0]["case_id"] == "legacy-1"
            assert cases[0]["expected_label"] == "semantic/needs_more_content"

            with sqlite3.connect(str(old_db)) as c:
                cols = {row[1] for row in c.execute("PRAGMA table_info(replay_cases)")}
                indexes = {
                    row[0]
                    for row in c.execute(
                        "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='replay_cases'"
                    )
                }
            assert "run_id" in cols and "trace_id" in cols
            assert "idx_replay_run" in indexes
            assert "idx_replay_trace" in indexes
        finally:
            decision_store.configure(None)

    def test_fresh_db_has_columns_and_indexes(self, tmp_path: Path):
        fresh_db = tmp_path / "fresh.db"
        decision_store.configure(str(fresh_db))
        try:
            decision_store.record_replay_case(
                ReplayCase(case_id="fresh-1", run_id="r1", trace_id="t1", expected_label="x")
            )
            with sqlite3.connect(str(fresh_db)) as c:
                cols = {row[1] for row in c.execute("PRAGMA table_info(replay_cases)")}
                indexes = {
                    row[0]
                    for row in c.execute(
                        "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='replay_cases'"
                    )
                }
                row = c.execute("SELECT run_id, trace_id FROM replay_cases WHERE case_id='fresh-1'").fetchone()
            assert "run_id" in cols and "trace_id" in cols
            assert "idx_replay_run" in indexes and "idx_replay_trace" in indexes
            assert row == ("r1", "t1")
        finally:
            decision_store.configure(None)


# ---------------------------------------------------------------------------
# c. case_id != trace_id join
# ---------------------------------------------------------------------------


class TestCaseIdNotTrace:
    def test_labeled_row_joins_on_trace_not_case_id(self, hermetic_stores):
        decision_store.record_event(_make_event("R", "T1", event_id="ev-r1"))
        _insert_jev("R", "T1", question="result_usable")
        case = ReplayCase(
            case_id=str(uuid.uuid4()),  # random uuid — must NOT be used as trace
            run_id="R",
            trace_id="T1",
            domain="fetch",
            expected_label="semantic/result_usable",
            label_source="human_verified",
        )
        decision_store.record_replay_case(case)

        rows = build_labeled_rows("R")
        rs_rows = rows["result_usable"]
        assert len(rs_rows) == 1
        row = rs_rows[0]
        assert row.ground_truth is True
        assert row.trace_id == "T1"
        assert row.trace_id != case.case_id
        assert row.run_id == "R"


# ---------------------------------------------------------------------------
# d. objective materialization
# ---------------------------------------------------------------------------


_RESCUED_FACTS = {
    "status": "error",
    "primary_hard_signal": "TRANSPORT_FAILURE",
    "browser_attempted": True,
    "browser_success": True,
    "primary_extraction_success": False,
    "final_extraction_success": True,
    "primary_content_chars": 0,
    "browser_content_chars": 900,
    "final_content_chars": 900,
    "content_gain_chars": 900,
    "truncated": False,
    "continuation_available": False,
    "fallback_attempted": False,
    "fallback_success": False,
}


class TestObjectiveMaterialization:
    def test_deterministic_case_ids_and_idempotency(self, hermetic_stores):
        # Production browser-rescue facts (browser attempted, browser succeeded,
        # primary objectively failed) now MINT a browser-escalation-warranted
        # needs_escalation objective case — that is exactly the browser-specific
        # rescue evidence the question asks about. result_usable NO is also made.
        decision_store.record_event(_make_event("run-obj", "t-obj", event_id="obj-ev-1", outcome=dict(_RESCUED_FACTS)))

        n = materialize_objective_replay_cases("run-obj")
        assert n == 2  # result_usable NO + needs_escalation browser-escalation YES
        cases = decision_store.load_replay_cases(run_id="run-obj")
        by_id = {c["case_id"]: c for c in cases}

        assert set(by_id) == {"obj-ev-1:result_usable", "obj-ev-1:needs_escalation"}
        ru = by_id["obj-ev-1:result_usable"]
        assert ru["run_id"] == "run-obj"
        assert ru["trace_id"] == "t-obj"
        assert ru["domain"] == "fetch"
        assert ru["expected_label"] == "semantic/result_not_usable"
        assert ru["label_source"] == "objective_outcome"
        assert ru["label_confidence"] > 0
        assert ru["observed_outcome"]["browser_success"] is True
        assert ru["production_decision"]["deterministic_action"] == "ACCEPT"
        ne = by_id["obj-ev-1:needs_escalation"]
        assert ne["expected_label"] == "semantic/browser_escalation_warranted"
        assert ne["label_source"] == "objective_outcome"

        # Idempotent: re-run replaces, never duplicates.
        n2 = materialize_objective_replay_cases("run-obj")
        assert n2 == 2
        assert len(decision_store.load_replay_cases(run_id="run-obj")) == 2

    def test_search_success_creates_no_semantic_case(self, hermetic_stores):
        search_event = DecisionEvent(
            event_id="search-ev-1",
            run_id="run-search",
            trace_id="t-search",
            domain=DecisionDomain.SEARCH,
            stage=DecisionStage.FINAL,
            outcome_features={"status": "success", "result_count": 8, "provider_attempt_count": 2},
        )
        decision_store.record_event(search_event)
        written = materialize_objective_replay_cases("run-search")
        cases = decision_store.load_replay_cases(run_id="run-search")
        case_ids = {c["case_id"] for c in cases}
        assert written == 0
        assert not any("result_relevant" in cid for cid in case_ids)
        assert not any("needs_escalation" in cid or "result_usable" in cid for cid in case_ids)


# ---------------------------------------------------------------------------
# f. run-specific replay loading
# ---------------------------------------------------------------------------


class TestRunScopedReplayLoading:
    def test_load_filtered_by_run(self, hermetic_stores):
        decision_store.record_replay_case(
            ReplayCase(case_id="ra1", run_id="run-A", trace_id="ta", expected_label="semantic/needs_more_content")
        )
        decision_store.record_replay_case(
            ReplayCase(case_id="rb1", run_id="run-B", trace_id="tb", expected_label="semantic/result_not_usable")
        )
        a_rows = decision_store.load_replay_cases(run_id="run-A")
        b_rows = decision_store.load_replay_cases(run_id="run-B")
        assert {c["case_id"] for c in a_rows} == {"ra1"}
        assert {c["case_id"] for c in b_rows} == {"rb1"}
        # domain + run compose.
        assert decision_store.load_replay_cases(domain="search", run_id="run-A") == []
        # default keeps prior global behavior.
        assert {c["case_id"] for c in decision_store.load_replay_cases()} == {"ra1", "rb1"}


# ---------------------------------------------------------------------------
# g. evaluation-only process run-id setter
# ---------------------------------------------------------------------------


class TestSetProcessRunIdForEvaluation:
    def test_patches_env_and_bound_globals(self, monkeypatch: pytest.MonkeyPatch):
        # Pre-import the modules that bound PROCESS_RUN_ID by value.
        from webscout_mcp import fetch_service, jev_shadow, search_service

        # Snapshot EVERY original value via monkeypatch so teardown restores the
        # exact bound ids (jev_shadow / runtime_context independently generate
        # their own random ids at import; never restore one module's id onto
        # another).
        monkeypatch.setattr(runtime_context, "PROCESS_RUN_ID", runtime_context.PROCESS_RUN_ID)
        monkeypatch.setattr(fetch_service, "PROCESS_RUN_ID", fetch_service.PROCESS_RUN_ID)
        monkeypatch.setattr(search_service, "PROCESS_RUN_ID", search_service.PROCESS_RUN_ID)
        monkeypatch.setattr(jev_shadow, "PROCESS_RUN_ID", jev_shadow.PROCESS_RUN_ID)
        for var in ("WEBSCOUT_RUN_ID", "JEV_RUN_ID"):
            if var in os.environ:
                monkeypatch.setenv(var, os.environ[var])
            else:
                monkeypatch.delenv(var, raising=False)

        runtime_context.set_process_run_id_for_evaluation("eval-run-xyz")

        assert runtime_context.PROCESS_RUN_ID == "eval-run-xyz"
        assert os.environ["WEBSCOUT_RUN_ID"] == "eval-run-xyz"
        assert os.environ["JEV_RUN_ID"] == "eval-run-xyz"
        # Already-imported bound names were patched (not just the global).
        assert fetch_service.PROCESS_RUN_ID == "eval-run-xyz"
        assert search_service.PROCESS_RUN_ID == "eval-run-xyz"
        assert jev_shadow.PROCESS_RUN_ID == "eval-run-xyz"
