"""The benchmark script must stay runnable, and must actually catch a regression.

A benchmark that always reports 100% is worse than none: it manufactures confidence. So
alongside a smoke test that the script runs, there is a test that deliberately breaks one
behaviour and asserts the benchmark notices.

The regression used is the v2.1 defect itself - a monitor that does not persist its
baseline. Reproducing it here proves the scenario is load-bearing rather than decorative.
"""

from __future__ import annotations

import asyncio
import json
import pathlib
import subprocess
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "benchmark_tools.py"


def _run_benchmark(tmp_path: pathlib.Path) -> dict:
    out = tmp_path / "report.json"
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--strict", "--json", str(out)],
        capture_output=True,
        text=True,
        timeout=300,
        cwd=str(REPO),
    )
    assert proc.returncode == 0, f"benchmark failed\nstdout:\n{proc.stdout[-2000:]}\nstderr:\n{proc.stderr[-2000:]}"
    return json.loads(out.read_text(encoding="utf-8"))


def test_benchmark_script_runs_and_passes():
    import tempfile

    report = _run_benchmark(pathlib.Path(tempfile.mkdtemp()))
    assert report["failed"] == 0, report["scenarios"]
    assert report["total"] >= 12, report["total"]
    assert report["pass_rate"] == 100.0


def test_every_scenario_states_what_it_proves():
    """A scenario whose name is the only description cannot explain a failure."""
    import tempfile

    report = _run_benchmark(pathlib.Path(tempfile.mkdtemp()))
    for scenario in report["scenarios"]:
        assert scenario["proves"], f"{scenario['name']} has no description"
        assert len(scenario["proves"]) > 10, scenario


def test_skips_carry_a_reason():
    """Skipping silently would let coverage quietly shrink."""
    import tempfile

    report = _run_benchmark(pathlib.Path(tempfile.mkdtemp()))
    for entry in report["skipped"]:
        assert entry["reason"], f"{entry['name']} skipped without a reason"
        assert len(entry["reason"]) > 20, entry


def test_the_benchmark_catches_a_broken_baseline(tmp_path):
    """Break persistence the way v2.1 was broken, and confirm the scenario fails.

    `_save_history` is what carries the comparison baseline to disk. Making it a no-op
    reproduces the original defect: a fresh process starts with no baseline, so no change
    can ever be reported. If the benchmark still passes, its persistence scenario is
    decorative.
    """
    shim = tmp_path / "run_broken.py"
    report = tmp_path / "report.json"
    shim.write_text(
        "import runpy, sys\n"
        "from webscout_mcp.extras.monitor import WebMonitor\n"
        "WebMonitor._save_history = lambda self: None\n"
        f"sys.argv = [{str(SCRIPT)!r}, '--strict', '--json', {str(report)!r}]\n"
        f"runpy.run_path({str(SCRIPT)!r}, run_name='__main__')\n",
        encoding="utf-8",
    )
    proc = subprocess.run(
        [sys.executable, str(shim)],
        capture_output=True,
        text=True,
        timeout=300,
        cwd=str(REPO),
        env={**__import__("os").environ, "PYTHONPATH": str(REPO)},
    )
    assert proc.returncode == 1, (
        "the benchmark passed even though the monitor no longer persists its baseline; "
        f"the persistence scenario is not load-bearing\nstdout:\n{proc.stdout[-1500:]}"
    )
    assert "web_monitor" in proc.stdout, proc.stdout[-1500:]
    assert report.exists(), "a failing run should still write its report"
    data = json.loads(report.read_text(encoding="utf-8"))
    assert data["failed"] >= 1, data
    assert any("web_monitor" in s["name"] for s in data["scenarios"] if not s["passed"]), data


def test_report_shape_is_stable():
    """The JSON is consumed by CI and by humans; its keys should not drift silently."""
    import tempfile

    report = _run_benchmark(pathlib.Path(tempfile.mkdtemp()))
    # `degraded` was added with the live mode: a real site answering with a challenge page
    # is information, not a failure, and needs its own bucket.
    assert set(report) == {
        "total",
        "passed",
        "failed",
        "pass_rate",
        "scenarios",
        "skipped",
        "degraded",
    }
    for scenario in report["scenarios"]:
        assert set(scenario) == {"name", "passed", "proves", "detail", "error"}


def test_dns_probe_reports_the_reason_it_failed():
    """A skip must say what was measured, not merely that something was skipped.

    The probe returns the resolved address so a reader can tell a fake-IP environment from
    a genuinely unreachable one.
    """
    sys.path.insert(0, str(REPO / "scripts"))
    import importlib.util

    spec = importlib.util.spec_from_file_location("bench", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    # Register before executing: `@dataclass` resolves annotations through
    # sys.modules[cls.__module__], which is null for an unregistered module and raises
    # AttributeError on the first dataclass in the file.
    sys.modules["bench"] = module
    spec.loader.exec_module(module)

    ok, reason = module.has_real_dns()
    assert isinstance(ok, bool)
    assert reason, "the probe must explain itself"
    if not ok:
        # Either an address from a reserved range, or a resolution failure.
        assert "reserved" in reason or "cannot resolve" in reason, reason


def test_network_scenarios_are_not_hardcoded_to_skip():
    """On a machine with real DNS these must run, not be skipped by name.

    Hardcoding the skip would quietly shrink coverage in CI, where DNS works - exactly
    where the check is most valuable.
    """
    source = SCRIPT.read_text(encoding="utf-8")
    assert "has_real_dns()" in source
    assert "if real_dns:" in source, "the skip decision must be conditional"
    assert 'report.skip(\n            "web_search",\n            f"needs a live search backend' in source or (
        "web_search" in source and "if real_dns" in source
    ), "web_search must be attempted when the environment allows it"


# --- live mode --------------------------------------------------------


def test_live_flag_exists_and_is_opt_in():
    """Live scenarios must never run by default: they touch the network."""
    source = SCRIPT.read_text(encoding="utf-8")
    assert '"--live"' in source
    assert "LIVE_TARGETS" in source
    # the default invocation must not enable it
    assert 'add_argument(\n        "--live",\n        action="store_true"' in source or (
        '"--live"' in source and 'action="store_true"' in source
    )


def test_live_verdicts_are_graded():
    """A real site declining to serve us is `degraded`, not `fail`.

    Counting an anti-bot wall as a product failure would make the number meaningless and
    invite tuning it until it looked good.
    """
    source = SCRIPT.read_text(encoding="utf-8")
    assert "degraded" in source
    # only a contract break blocks
    assert 'counts["fail"]' in source
    assert 'counts["degraded"]' not in source.split("if args.strict")[-1], "degraded must not gate the run"


def test_live_gate_probes_actual_reachability():
    """System DNS is the wrong question: this machine resolves to 198.18.0.x yet fetches fine.

    Pinned because using `has_real_dns` as the live gate skipped scenarios that work.
    """
    source = SCRIPT.read_text(encoding="utf-8")
    assert "can_reach_internet" in source
    assert "reached example.com" in source or "status" in source


def test_degraded_bucket_is_reported_separately():
    import tempfile

    report = _run_benchmark(pathlib.Path(tempfile.mkdtemp()))
    assert "degraded" in report
    assert isinstance(report["degraded"], list)


# --- section membership ----------------------------------------------


def test_broken_links_is_a_live_scenario_not_a_local_one():
    """It cannot be a local scenario, and pretending otherwise broke the local rate.

    `BrokenLinkChecker` pins its TCP connection to the IPs from its SSRF check, so it can
    never use a loopback fixture, and it does not share the fetch_service pipeline. When it
    sat in the local section gated by a DNS probe, the probe opened on a machine whose DNS
    had started resolving public addresses and the local rate read 15/16 - an environment
    property dressed up as a product regression.
    """
    source = SCRIPT.read_text(encoding="utf-8")
    local, _, live = source.partition("async def _run_live")
    assert "broken_links" not in local, "it must not be a local-section scenario"
    assert "broken_links" in live, "it belongs to the live section"
    assert "_check_broken_links" in live


def test_broken_links_skips_on_a_tls_refusal_not_fails():
    """A network that rejects TLS to a bare IP is not a defect in the tool.

    Measured here: `https://104.20.23.154/` with `Host: example.com` gives
    SSLV3_ALERT_HANDSHAKE_FAILURE while `https://example.com/` returns 200. The pin exists
    to prevent DNS rebinding, so the constraint is the network's, not the code's.
    """
    source = SCRIPT.read_text(encoding="utf-8")
    assert "transport_refused_tls" in source
    assert "SSLV3_ALERT" in source
    # the skip must name the reason rather than swallow it
    assert "SSRF-pinned transport connects to a bare IP" in source


def test_live_skips_are_visible_in_output_and_json():
    """A live skip that vanishes from the report is coverage shrinking unseen."""
    source = SCRIPT.read_text(encoding="utf-8")
    assert "for name, reason in live_report.skipped" in source
    assert '"skipped": [{"name": n, "reason": why} for n, why in live_report.skipped]' in source
    assert "skipped_count" in source
