"""Hermetic tests for eval_preflight.

No real network: the Crawl4AI probe and provider counts are monkeypatched.
Central invariant: per-capability READY/BLOCKED verdicts with specific reasons,
and NO secret (credential / token / cookie) ever appears in the report.
"""

from __future__ import annotations

import json

from webscout_mcp import eval_preflight

SENTINEL_KEY = "sk-SENTINEL-secret-123"
SENTINEL_TOKEN = "crawl4ai-SENTINEL-token-456"


def _base_patches(monkeypatch):
    # Stable, fast environment: two search providers, no sidecar probe by default.
    monkeypatch.setattr(eval_preflight, "_search_provider_count", lambda cfg: 2)
    monkeypatch.setattr(eval_preflight, "_crawl4ai_reachable", lambda url, timeout=1.5: False)


def test_jev_blocked_when_sdk_missing(monkeypatch):
    _base_patches(monkeypatch)
    monkeypatch.setattr(eval_preflight, "_typesafe_sdk_importable", lambda: False)
    monkeypatch.setattr(eval_preflight, "_credential_present", lambda cfg: False)
    monkeypatch.setenv("JEV_ENABLED", "false")

    report = eval_preflight.run_preflight()
    v = report["capabilities"]["jev_shadow"]
    assert v["status"] == "BLOCKED"
    joined = " ".join(v["reasons"])
    assert "SDK" in joined
    assert "credential" in joined


def test_jev_blocked_when_credential_missing_only(monkeypatch):
    _base_patches(monkeypatch)
    monkeypatch.setattr(eval_preflight, "_typesafe_sdk_importable", lambda: True)
    monkeypatch.setattr(eval_preflight, "_credential_present", lambda cfg: False)

    report = eval_preflight.run_preflight()
    v = report["capabilities"]["jev_shadow"]
    assert v["status"] == "BLOCKED"
    assert any("credential" in r.lower() for r in v["reasons"])


def test_jev_ready_with_sdk_and_credential(monkeypatch):
    _base_patches(monkeypatch)
    monkeypatch.setattr(eval_preflight, "_typesafe_sdk_importable", lambda: True)
    monkeypatch.setattr(eval_preflight, "_credential_present", lambda cfg: True)
    monkeypatch.setenv("JEV_ENABLED", "false")

    report = eval_preflight.run_preflight()
    v = report["capabilities"]["jev_shadow"]
    assert v["status"] == "READY"
    # Note about runtime-disabled even when ready.
    assert any("JEV_ENABLED" in r for r in v["reasons"])


def test_search_blocked_when_no_providers(monkeypatch):
    _base_patches(monkeypatch)
    monkeypatch.setattr(eval_preflight, "_search_provider_count", lambda cfg: 0)

    report = eval_preflight.run_preflight()
    v = report["capabilities"]["search_live"]
    assert v["status"] == "BLOCKED"
    assert any("no search provider" in r for r in v["reasons"])


def test_search_ready_with_providers(monkeypatch):
    _base_patches(monkeypatch)
    report = eval_preflight.run_preflight()
    assert report["capabilities"]["search_live"]["status"] == "READY"


def test_browser_blocked_when_sidecar_unreachable(monkeypatch):
    _base_patches(monkeypatch)
    # Force the browser backend to report "configured" while the probe fails.
    monkeypatch.setenv("CRAWL4AI_ENABLED", "true")
    monkeypatch.setenv("CRAWL4AI_BASE_URL", "http://localhost:11235")
    monkeypatch.setattr(eval_preflight, "_crawl4ai_reachable", lambda url, timeout=1.5: False)

    report = eval_preflight.run_preflight()
    v = report["capabilities"]["browser_counterfactual"]
    assert v["status"] == "BLOCKED"
    assert any("sidecar" in r for r in v["reasons"])


def test_browser_ready_when_configured_and_reachable(monkeypatch):
    _base_patches(monkeypatch)
    monkeypatch.setenv("CRAWL4AI_ENABLED", "true")
    monkeypatch.setenv("CRAWL4AI_BASE_URL", "http://localhost:11235")
    monkeypatch.setattr(eval_preflight, "_crawl4ai_reachable", lambda url, timeout=1.5: True)

    report = eval_preflight.run_preflight()
    v = report["capabilities"]["browser_counterfactual"]
    assert v["status"] == "READY"


def test_no_secret_leakage_in_json_or_text(monkeypatch):
    _base_patches(monkeypatch)
    monkeypatch.setattr(eval_preflight, "_typesafe_sdk_importable", lambda: True)
    monkeypatch.setattr(eval_preflight, "_credential_present", lambda cfg: True)
    monkeypatch.setenv("TYPESAFE_API_KEY", SENTINEL_KEY)
    monkeypatch.setenv("CRAWL4AI_API_TOKEN", SENTINEL_TOKEN)
    monkeypatch.setenv("CRAWL4AI_ENABLED", "true")
    monkeypatch.setenv("CRAWL4AI_BASE_URL", "http://localhost:11235")
    monkeypatch.setattr(eval_preflight, "_crawl4ai_reachable", lambda url, timeout=1.5: True)

    report = eval_preflight.run_preflight()
    blob = json.dumps(report, default=str)
    text = eval_preflight.to_text(report)

    assert SENTINEL_KEY not in blob
    assert SENTINEL_TOKEN not in blob
    assert SENTINEL_KEY not in text
    assert SENTINEL_TOKEN not in text

    # No secret-like keys anywhere in the structured report.
    def _scan(obj):
        if isinstance(obj, dict):
            for k, v in obj.items():
                kl = str(k).lower()
                assert not any(s in kl for s in ("authorization", "token", "cookie", "api_key", "apikey")), k
                _scan(v)
        elif isinstance(obj, list):
            for v in obj:
                _scan(v)

    _scan(report)
