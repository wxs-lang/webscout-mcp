"""Hermetic tests for the v1.5.0 Phase 2.1 UNIFIED evaluation CLI.

Covers (per task spec):
  a. --live executes the pipeline (runners awaited, materialize called, pack +
     report written); no real network.
  b. --report-only is zero-network / zero-service-construction and is run-scoped.
  c. mutually exclusive mode flags -> exit 2; no-flag default = report-only.
  d. --preflight prints text; all-READY -> 0, any BLOCKED -> 2.
  e. model metadata (model_pairs / model_requested / model_resolved / sdk_version).
  f. human import correlation: human_verified ReplayCases preserve run_id/trace_id
     and join via build_labeled_rows.
  g. scoped join gate: two runs in one DB; each report counts only its run.
  h. human pack builder: >=20 fetch + >=30 search rows with documented keys.
  i. no credential leakage into report/pack.
  j. status gating: insufficient counts -> INCOMPLETE flags; never "Phase 2
     complete"; READY only when both gates pass.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sqlite3
import sys
import time
import uuid
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from webscout_mcp import decision_store, eval_human, jev_store  # noqa: E402
from webscout_mcp.advisor_evaluator import build_labeled_rows  # noqa: E402
from webscout_mcp.replay_case import ReplayCase  # noqa: E402

spec = importlib.util.spec_from_file_location(
    "run_objective_evaluation", REPO / "scripts" / "run_objective_evaluation.py"
)
cli = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cli)  # type: ignore[union-attr]


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def isolated_stores(tmp_path, monkeypatch):
    """Point the global stores at throwaway tmp DBs; nothing touches production."""
    decision_db = tmp_path / "decision.db"
    jev_db = tmp_path / "jev.db"
    monkeypatch.setattr(decision_store, "_db_path", decision_db, raising=False)
    monkeypatch.setattr(jev_store, "_db_path", jev_db, raising=False)
    return tmp_path


def _seed_event(
    db_path: Path,
    *,
    run_id: str,
    trace_id: str,
    domain: str = "fetch",
    metadata: dict | None = None,
    outcome: dict | None = None,
) -> None:
    eid = f"{domain}-{trace_id}-{uuid.uuid4().hex[:8]}"
    with sqlite3.connect(str(db_path)) as c:
        c.execute(
            """INSERT INTO decision_events (
                schema_version, event_id, trace_id, run_id, domain, stage,
                subject, observed_status, deterministic_reason, deterministic_action,
                production_action, production_outcome, request_features,
                outcome_features, metadata, jev_call_id, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                "1.0",
                eid,
                trace_id,
                run_id,
                domain,
                "route",
                "",
                "ok",
                "OK",
                "ACCEPT",
                "ACCEPT",
                "ok",
                json.dumps({}),
                json.dumps(outcome or {}),
                json.dumps(metadata or {"jev_eligible": True, "jev_enabled": True}),
                "",
                time.time(),
            ),
        )


def _seed_jev(
    db_path: Path,
    *,
    run_id: str,
    trace_id: str,
    question: str,
    operation: str = "fetch",
    probability: float = 0.9,
    model_requested: str = "typesafe-small",
    model_resolved: str = "typesafe-small",
    position: int | None = None,
    timestamp: float | None = None,
) -> None:
    with sqlite3.connect(str(db_path)) as c:
        c.execute(
            """INSERT INTO jev_records (
                timestamp, trace_id, operation, jev_question, jev_decision,
                jev_probability, rule_decision, run_id, model_requested,
                model_resolved, position)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (
                timestamp if timestamp is not None else time.time(),
                trace_id,
                operation,
                question,
                1 if probability >= 0.5 else 0,
                probability,
                0,
                run_id,
                model_requested,
                model_resolved,
                position,
            ),
        )


def _make_run_db(out_dir: Path, run_id: str) -> tuple[Path, Path]:
    """Create an initialized per-run dir with decision.db + jev.db."""
    run_dir = out_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    ddb = run_dir / "decision.db"
    jdb = run_dir / "jev.db"
    decision_store.configure(ddb)
    jev_store.configure(jdb)
    return ddb, jdb


# ---------------------------------------------------------------------------
# c. mutually exclusive flags + default behavior
# ---------------------------------------------------------------------------


class TestModeFlags:
    def test_two_mode_flags_exit_2(self):
        with pytest.raises(SystemExit) as exc:
            cli.main(["--live", "--report-only"])
        assert exc.value.code == 2

    def test_live_and_preflight_exit_2(self):
        with pytest.raises(SystemExit) as exc:
            cli.main(["--live", "--preflight"])
        assert exc.value.code == 2

    def test_browser_counterfactual_requires_live(self):
        with pytest.raises(SystemExit) as exc:
            cli.main(["--with-browser-counterfactual"])
        assert exc.value.code == 2

    def test_default_no_flag_is_report_only(self, tmp_path, monkeypatch):
        out_dir = tmp_path / "out"
        ddb, jdb = _make_run_db(out_dir, "run-default")
        _seed_event(ddb, run_id="run-default", trace_id="t1")

        # If the live service builder were called, the test fails loudly.
        def boom(*a, **k):  # pragma: no cover - must not be called
            raise AssertionError("configure_eval_run must not run in report-only mode")

        monkeypatch.setattr(cli, "configure_eval_run", boom)
        rc = cli.main(["--run-id", "run-default", "--out-dir", str(out_dir)])
        assert rc == 0
        assert (out_dir / "run-default" / cli.REPORT_JSON).exists()


# ---------------------------------------------------------------------------
# d. preflight
# ---------------------------------------------------------------------------


class TestPreflight:
    def test_all_ready_returns_0(self, monkeypatch, capsys):
        monkeypatch.setattr(
            cli,
            "run_preflight",
            lambda: {
                "checks": {"a": True},
                "paths": {"decision_db": "/x"},
                "capabilities": {
                    "fetch_live": {"status": "READY", "reasons": []},
                    "search_live": {"status": "READY", "reasons": []},
                    "jev_shadow": {"status": "READY", "reasons": []},
                    "browser_counterfactual": {"status": "READY", "reasons": []},
                },
            },
        )
        rc = cli.main(["--preflight"])
        assert rc == 0
        assert "WebScout evaluation preflight" in capsys.readouterr().out

    def test_blocked_returns_2(self, monkeypatch):
        monkeypatch.setattr(
            cli,
            "run_preflight",
            lambda: {
                "checks": {},
                "paths": {},
                "capabilities": {
                    "fetch_live": {"status": "READY", "reasons": []},
                    "search_live": {"status": "READY", "reasons": []},
                    "jev_shadow": {"status": "BLOCKED", "reasons": ["no sdk"]},
                    "browser_counterfactual": {"status": "READY", "reasons": []},
                },
            },
        )
        rc = cli.main(["--preflight"])
        assert rc == 2


# ---------------------------------------------------------------------------
# a. --live pipeline
# ---------------------------------------------------------------------------


class TestLivePipeline:
    def test_live_runs_pipeline(self, tmp_path, monkeypatch):
        out_dir = tmp_path / "out"
        run_dir = out_dir / "runL"
        run_dir.mkdir(parents=True)
        ddb = run_dir / "decision.db"
        jdb = run_dir / "jev.db"
        decision_store.configure(ddb)
        jev_store.configure(jdb)

        calls: list[str] = []
        services = {
            "fetch_service": object(),
            "search_service": object(),
            "eval_dir": str(run_dir),
            "run_id": "runL",
        }

        def fake_configure(run_id, *, base_dir=None):
            calls.append("configure")
            assert run_id == "runL"
            return services

        async def fake_fetch(svc, run_id, *, limit=0, **kw):
            calls.append("fetch")
            assert run_id == "runL"
            return {"run_id": run_id, "total": 1, "succeeded": 1, "failed": 0, "results": []}

        async def fake_search(svc, run_id, *, limit=0, **kw):
            calls.append("search")
            return {"run_id": run_id, "total": 1, "succeeded": 1, "failed": 0, "result_rows": 10, "results": []}

        async def fake_cf(svc, run_id, *, limit=0):
            calls.append("browser_cf")
            return []

        async def fake_aclose(svc):
            calls.append("aclose")

        def fake_materialize(run_id):
            calls.append("materialize")
            return 7

        monkeypatch.setattr(cli, "configure_eval_run", fake_configure)
        monkeypatch.setattr(cli, "run_fetch_corpus", fake_fetch)
        monkeypatch.setattr(cli, "run_search_corpus", fake_search)
        monkeypatch.setattr(cli, "run_browser_counterfactual", fake_cf)
        monkeypatch.setattr(cli, "aclose_services", fake_aclose)
        monkeypatch.setattr(cli, "materialize_objective_replay_cases", fake_materialize)

        rc = cli.main(["--live", "--run-id", "runL", "--out-dir", str(out_dir), "--with-browser-counterfactual"])
        assert rc == 0
        assert calls[0] == "configure"
        assert "fetch" in calls and "search" in calls and "browser_cf" in calls
        # Jev must be drained BEFORE materialization / reading.
        assert calls.index("aclose") < calls.index("materialize")
        assert calls[-1] == "materialize"
        assert (run_dir / cli.REPORT_JSON).exists()
        report = json.loads((run_dir / cli.REPORT_JSON).read_text())
        assert report["run_id"] == "runL"

    def test_live_no_search_service_skips_search(self, tmp_path, monkeypatch):
        out_dir = tmp_path / "out"
        run_dir = out_dir / "runL2"
        run_dir.mkdir(parents=True)
        decision_store.configure(run_dir / "decision.db")
        jev_store.configure(run_dir / "jev.db")
        services = {"fetch_service": object(), "search_service": None, "eval_dir": str(run_dir), "run_id": "runL2"}

        async def fake_fetch(svc, run_id, *, limit=0, **kw):
            return {"run_id": run_id, "total": 1, "succeeded": 1, "failed": 0, "results": []}

        async def fake_aclose(svc):
            return None

        monkeypatch.setattr(cli, "configure_eval_run", lambda *a, **k: services)
        monkeypatch.setattr(cli, "run_fetch_corpus", fake_fetch)

        async def boom(*a, **k):  # pragma: no cover
            raise AssertionError("search runner must not be called when search_service is None")

        monkeypatch.setattr(cli, "run_search_corpus", boom)
        monkeypatch.setattr(cli, "aclose_services", fake_aclose)
        monkeypatch.setattr(cli, "materialize_objective_replay_cases", lambda rid: 0)
        rc = cli.main(["--live", "--run-id", "runL2", "--out-dir", str(out_dir)])
        assert rc == 0


# ---------------------------------------------------------------------------
# b. report-only: zero network, run-scoped
# ---------------------------------------------------------------------------


class TestReportOnly:
    def test_report_only_no_services(self, tmp_path, monkeypatch):
        out_dir = tmp_path / "out"
        ddb, jdb = _make_run_db(out_dir, "runR")
        for i in range(3):
            _seed_event(ddb, run_id="runR", trace_id=f"ft{i}", domain="fetch")
            _seed_event(ddb, run_id="runR", trace_id=f"st{i}", domain="search")

        def boom(*a, **k):  # pragma: no cover
            raise AssertionError("live service builder/runner leaked into report-only")

        monkeypatch.setattr(cli, "configure_eval_run", boom)
        monkeypatch.setattr(cli, "run_fetch_corpus", boom)
        monkeypatch.setattr(cli, "run_search_corpus", boom)
        monkeypatch.setattr(cli, "run_browser_counterfactual", boom)

        rc = cli.main(["--report-only", "--run-id", "runR", "--out-dir", str(out_dir)])
        assert rc == 0
        report = json.loads((out_dir / "runR" / cli.REPORT_JSON).read_text())
        assert report["run_id"] == "runR"
        assert report["counts"]["events_total"] == 6
        assert report["counts"]["fetch_events"] == 3
        assert report["decision_db"].endswith(str(out_dir / "runR" / "decision.db"))
        assert (out_dir / "runR" / cli.REPORT_MD).exists()


# ---------------------------------------------------------------------------
# g. scoped join gate
# ---------------------------------------------------------------------------


class TestScopedJoin:
    def test_two_runs_one_db(self, tmp_path, monkeypatch):
        out_dir = tmp_path / "out"
        # One shared decision.db containing BOTH runs.
        runA_dir = out_dir / "runA"
        runA_dir.mkdir(parents=True)
        ddb = runA_dir / "decision.db"
        jdb = runA_dir / "jev.db"
        decision_store.configure(ddb)
        jev_store.configure(jdb)
        for i in range(2):
            _seed_event(ddb, run_id="runA", trace_id=f"a{i}")
            _seed_jev(jdb, run_id="runA", trace_id=f"a{i}", question="needs_escalation")
        for i in range(4):
            _seed_event(ddb, run_id="runB", trace_id=f"b{i}")
            _seed_jev(jdb, run_id="runB", trace_id=f"b{i}", question="needs_escalation")

        # runA report: only A's counts.
        rc = cli.main(["--report-only", "--run-id", "runA", "--out-dir", str(out_dir)])
        assert rc == 0
        repA = json.loads((runA_dir / cli.REPORT_JSON).read_text())
        assert repA["counts"]["events_total"] == 2
        assert repA["join_report"]["advisor_enabled_decisions"] == 2

        # runB shares the SAME physical DB files (symlinked into its own per-run
        # dir). report-only now FAILS CLOSED when a run's own DBs are absent; the
        # scoped report must still only see runB's events.
        runB_dir = out_dir / "runB"
        runB_dir.mkdir(parents=True)
        os.symlink(ddb, runB_dir / "decision.db")
        os.symlink(jdb, runB_dir / "jev.db")
        rc = cli.main(["--report-only", "--run-id", "runB", "--out-dir", str(out_dir)])
        assert rc == 0
        repB = json.loads((runB_dir / cli.REPORT_JSON).read_text())
        assert repB["counts"]["events_total"] == 4
        assert repB["join_report"]["advisor_enabled_decisions"] == 4


# ---------------------------------------------------------------------------
# e. model metadata
# ---------------------------------------------------------------------------


class TestModelMetadata:
    def test_model_metadata(self, tmp_path, monkeypatch):
        out_dir = tmp_path / "out"
        ddb, jdb = _make_run_db(out_dir, "runM")
        _seed_event(ddb, run_id="runM", trace_id="mt")
        _seed_jev(
            jdb,
            run_id="runM",
            trace_id="mt",
            question="result_usable",
            model_requested="typesafe-a",
            model_resolved="typesafe-a",
        )
        _seed_jev(
            jdb,
            run_id="runM",
            trace_id="mt",
            question="needs_escalation",
            model_requested="typesafe-a",
            model_resolved="typesafe-a",
        )
        _seed_jev(
            jdb,
            run_id="runM",
            trace_id="mt2",
            question="result_relevant",
            model_requested="typesafe-b",
            model_resolved="typesafe-b",
        )

        cli.main(["--report-only", "--run-id", "runM", "--out-dir", str(out_dir)])
        report = json.loads((out_dir / "runM" / cli.REPORT_JSON).read_text())
        assert report["model_pairs"] == [["typesafe-a", "typesafe-a"], ["typesafe-b", "typesafe-b"]]
        assert report["model_requested"] == "typesafe-a"  # most common
        assert report["model_resolved"] == "typesafe-a"
        assert "sdk_version" in report
        assert report["sdk_version"]  # present (may be a version or "not-installed")


# ---------------------------------------------------------------------------
# h. human pack builder
# ---------------------------------------------------------------------------


class TestHumanPack:
    def test_pack_row_counts_and_keys(self, tmp_path):
        fetch_results = [
            {
                "url": f"https://ex.com/{i}",
                "trace_id": f"ft{i}",
                "status": "success",
                "status_code": 200,
                "chars": 500,
                "title": f"T{i}",
                "excerpt": f"e{i}",
            }
            for i in range(25)
        ]
        # 3 queries x 10 rows = 30 search rows.
        search_results = [
            {
                "query": f"q{i}",
                "trace_id": f"st{i}",
                "rows": [
                    {"position": p + 1, "title": f"t{i}{p}", "snippet": f"s{i}{p}", "url": f"u{i}{p}"}
                    for p in range(10)
                ],
            }
            for i in range(3)
        ]
        pack = eval_human.build_human_review_pack("runP", tmp_path, fetch_results, search_results)
        rows = [json.loads(line) for line in pack.read_text().splitlines() if line.strip()]
        fetch_rows = [r for r in rows if r["question"] == "result_usable"]
        search_rows = [r for r in rows if r["question"] == "result_relevant"]
        assert len(fetch_rows) >= 20
        assert len(search_rows) >= 30
        for r in fetch_rows:
            assert r["case_id"].startswith("human:")
            assert r["run_id"] == "runP" and r["trace_id"] and r["domain"] == "fetch"
            assert set(r["context"]) >= {"url", "title", "chars", "status", "excerpt"}
            assert r["expected_label"] == ""
        for r in search_rows:
            assert r["case_id"].endswith(f":p{r['context']['position']}")
            assert r["domain"] == "search"
            assert set(r["context"]) >= {"query", "position", "title", "snippet", "url"}

    def test_pack_skips_error_and_untraced(self, tmp_path):
        fetch_results = [
            {"url": "https://x", "trace_id": "", "status": "success", "chars": 100},
            {"url": "https://y", "trace_id": "t", "status": "error", "chars": 0},
        ]
        pack = eval_human.build_human_review_pack("runP2", tmp_path, fetch_results, [])
        rows = [json.loads(line) for line in pack.read_text().splitlines() if line.strip()]
        assert rows == []


# ---------------------------------------------------------------------------
# f. human import correlation
# ---------------------------------------------------------------------------


class TestHumanImport:
    def test_import_correlates_and_joins(self, tmp_path):
        out_dir = tmp_path / "out"
        ddb, jdb = _make_run_db(out_dir, "runH")
        trace = "human-trace-1"
        _seed_event(ddb, run_id="runH", trace_id=trace, domain="fetch")
        _seed_jev(jdb, run_id="runH", trace_id=trace, question="result_usable", probability=0.4)

        pack_rows = [
            {
                "case_id": f"human:{trace}:result_usable",
                "run_id": "runH",
                "trace_id": trace,
                "domain": "fetch",
                "question": "result_usable",
                "context": {"url": "https://ex.com", "title": "T", "chars": 10, "status": "success", "excerpt": ""},
                "expected_label": "semantic/result_not_usable",
            }
        ]
        labeled = tmp_path / "labeled.jsonl"
        labeled.write_text("\n".join(json.dumps(r) for r in pack_rows) + "\n")

        n = eval_human.import_human_labels("runH", labeled)
        assert n == 1
        rc = cli.main(["--report-only", "--run-id", "runH", "--out-dir", str(out_dir)])
        assert rc == 0

        replay = decision_store.load_replay_cases(run_id="runH")
        assert len(replay) == 1
        assert replay[0]["label_source"] == "human_verified"
        assert replay[0]["trace_id"] == trace and replay[0]["run_id"] == "runH"
        assert replay[0]["expected_label"] == "semantic/result_not_usable"

        # build_labeled_rows must join the human label to the Jev row.
        rows = build_labeled_rows("runH")
        usable = [r for r in rows["result_usable"] if r.label_source == "human_verified"]
        assert len(usable) == 1
        assert usable[0].ground_truth is False  # result_not_usable maps to False
        assert usable[0].trace_id == trace

    def test_import_skips_unlabeled_rows(self, tmp_path):
        out_dir = tmp_path / "out"
        _make_run_db(out_dir, "runH2")
        labeled = tmp_path / "l.jsonl"
        labeled.write_text(
            json.dumps(
                {
                    "case_id": "human:x",
                    "run_id": "runH2",
                    "trace_id": "x",
                    "domain": "fetch",
                    "question": "result_usable",
                    "context": {},
                    "expected_label": "",
                }
            )
            + "\n"
        )
        assert eval_human.import_human_labels("runH2", labeled) == 0


# ---------------------------------------------------------------------------
# i. no credential leakage
# ---------------------------------------------------------------------------


class TestNoCredentialLeak:
    def test_no_sentinel_in_report_or_pack(self, tmp_path, monkeypatch):
        monkeypatch.setenv("TYPESAFE_API_KEY", "SENTINEL_SECRET_TOKEN_XYZ")
        monkeypatch.setenv("CRAWL4AI_TOKEN", "SENTINEL_CRAWL_TOKEN_ABC")
        out_dir = tmp_path / "out"
        ddb, jdb = _make_run_db(out_dir, "runS")
        _seed_event(ddb, run_id="runS", trace_id="st")
        _seed_jev(jdb, run_id="runS", trace_id="st", question="result_usable")

        cli.main(["--report-only", "--run-id", "runS", "--out-dir", str(out_dir)])
        jtext = (out_dir / "runS" / cli.REPORT_JSON).read_text()
        mtext = (out_dir / "runS" / cli.REPORT_MD).read_text()

        pack = eval_human.build_human_review_pack(
            "runS",
            out_dir / "runS",
            [
                {
                    "url": "https://ex.com",
                    "trace_id": "st",
                    "status": "success",
                    "chars": 10,
                    "title": "T",
                    "excerpt": "hello",
                }
            ],
            [],
        )
        ptext = pack.read_text()
        for blob in (jtext, mtext, ptext):
            assert "SENTINEL_SECRET_TOKEN_XYZ" not in blob
            assert "SENTINEL_CRAWL_TOKEN_ABC" not in blob


# ---------------------------------------------------------------------------
# j. status gating
# ---------------------------------------------------------------------------


class TestStatusGating:
    def test_insufficient_counts_incomplete(self, tmp_path):
        out_dir = tmp_path / "out"
        _make_run_db(out_dir, "runEmpty")  # no events/jev/replay
        cli.main(["--report-only", "--run-id", "runEmpty", "--out-dir", str(out_dir)])
        report = json.loads((out_dir / "runEmpty" / cli.REPORT_JSON).read_text())
        status = report["status"]
        assert "PHASE2_REAL_EVAL_INCOMPLETE" in status
        assert "HUMAN_EVAL_INCOMPLETE" in status
        assert "Phase 2 complete" not in json.dumps(report)

    def test_ready_when_both_gates_pass(self, tmp_path):
        out_dir = tmp_path / "out"
        ddb, jdb = _make_run_db(out_dir, "runFull")

        # fetch>=60, search>=40, search result_relevant predictions>=100, browser cf>=20.
        for i in range(60):
            _seed_event(ddb, run_id="runFull", trace_id=f"f{i}", domain="fetch")
        for i in range(40):
            _seed_event(ddb, run_id="runFull", trace_id=f"s{i}", domain="search", outcome={"result_count": 3})
        for i in range(60):
            _seed_jev(jdb, run_id="runFull", trace_id=f"f{i}", question="needs_escalation", operation="fetch")
        # 120 result_relevant predictions across the 40 search traces, keyed by
        # result position (the real gate counts predictions, not result rows).
        for i in range(120):
            _seed_jev(
                jdb,
                run_id="runFull",
                trace_id=f"s{i % 40}",
                question="result_relevant",
                operation="search",
                position=(i % 3) + 1,
            )

        # Browser counterfactual artifact with 24 cases.
        run_dir = out_dir / "runFull"
        (run_dir / "browser-counterfactual.jsonl").write_text(
            "\n".join(json.dumps({"case_id": f"cf{i}"}) for i in range(24)) + "\n"
        )

        # Human labels: >=20 result_usable, >=30 result_relevant.
        for i in range(20):
            decision_store.record_replay_case(
                ReplayCase(
                    case_id=f"human:f{i}:result_usable",
                    run_id="runFull",
                    trace_id=f"f{i}",
                    domain="fetch",
                    input_features={"question": "result_usable"},
                    expected_label="semantic/result_usable",
                    label_source="human_verified",
                )
            )
        for i in range(30):
            decision_store.record_replay_case(
                ReplayCase(
                    case_id=f"human:s{i}:result_relevant",
                    run_id="runFull",
                    trace_id=f"s{i}",
                    domain="search",
                    input_features={"question": "result_relevant"},
                    expected_label="semantic/result_relevant",
                    label_source="human_verified",
                )
            )

        cli.main(["--report-only", "--run-id", "runFull", "--out-dir", str(out_dir)])
        report = json.loads((run_dir / cli.REPORT_JSON).read_text())
        assert report["status"] == "READY"
        assert report["real_run_gate"]["passed_join_coverage"] is True
        assert report["human_gate"]["passed_fetch_usable"] is True
        assert report["human_gate"]["passed_search_relevance"] is True
