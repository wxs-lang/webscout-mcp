"""The evaluation corpus must not contain hosts that fail on their own.

A corpus entry that cannot be fetched reliably measures the network, not the
pipeline. neverssl.com was one: eight direct HTTP attempts all returned
RemoteProtocolError after 6-8 seconds. Its A/B latency swung between 1.3s and
20.3s against a 78ms baseline for byte-identical content (1168 chars both arms),
and that single case was enough to flip the G3 latency gate.

Removing it is not loosening a gate - the gate still compares the pipeline
against the baseline for every remaining URL. It removes a measurement of
nothing.

These tests keep the exclusion honest: the reason is recorded, the corpus
fingerprint changes so old verdicts are not silently compared against a new
corpus, and the removed host cannot quietly come back.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

CORPUS = Path(__file__).resolve().parents[1] / "scripts" / "eval_corpus" / "fetch_urls.json"


@pytest.fixture(scope="module")
def corpus() -> dict:
    return json.loads(CORPUS.read_text(encoding="utf-8"))


def test_corpus_parses_and_has_urls(corpus):
    assert corpus["urls"], "corpus must not be empty"
    for entry in corpus["urls"]:
        assert "url" in entry
        assert entry["url"].startswith("http")


def test_corpus_version_carries_the_exclusion(corpus):
    """Bumping the version marks that verdicts before and after are not comparable."""
    assert corpus["version"] == "v2", "changing a URL is a corpus change and must bump the version"


def test_corpus_size_contract_is_intact(corpus):
    """The unreliable host was replaced, not dropped.

    tests/test_objective_evaluation.py asserts the corpus has at least 60 entries,
    and the first attempt at this change broke it by deleting the host outright.
    Shrinking coverage silently is worse than removing one host loudly, so the
    replacement keeps the contract.
    """
    assert len(corpus["urls"]) >= 60, "the corpus size contract lives in test_objective_evaluation.py"


def test_unreliable_host_is_not_in_the_active_corpus(corpus):
    urls = [e["url"] for e in corpus["urls"]]
    assert not any("neverssl.com" in u for u in urls), "the unreliable host came back"


def test_every_exclusion_records_a_reason(corpus):
    """An entry removed without a stated reason is indistinguishable from a typo."""
    excluded = corpus.get("excluded", [])
    assert excluded, "the exclusion should be documented, not just applied"
    for entry in excluded:
        assert "url" in entry
        assert entry.get("reason"), f"exclusion of {entry.get('url')} has no reason"


def test_the_removed_host_is_the_one_we_measured(corpus):
    excluded = {e["url"] for e in corpus.get("excluded", [])}
    assert "https://neverssl.com/" in excluded


def test_the_replacement_host_is_present(corpus):
    """The point of a replacement is that coverage did not shrink."""
    urls = {e["url"] for e in corpus["urls"]}
    assert "https://www.w3.org/" in urls
    assert any(e.get("stratum") == "short_static" for e in corpus["urls"] if e["url"] == "https://www.w3.org/")


def test_corpus_still_covers_every_stratum(corpus):
    """Removing one URL must not empty a stratum used by the stratification."""
    strata = {e.get("stratum") for e in corpus["urls"]}
    for expected in ("short_static", "docs_spec", "article", "js_heavy"):
        assert expected in strata, f"stratum {expected} disappeared"


def test_short_static_still_has_enough_entries(corpus):
    n = sum(1 for e in corpus["urls"] if e.get("stratum") == "short_static")
    assert n >= 5, f"only {n} short_static entries left; the stratum is thinning"


def test_corpus_fingerprint_changes_with_content(tmp_path):
    """Old verdicts record a fingerprint; changing the corpus must change it."""
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from webscout_mcp.ab_eval import corpus_fingerprint

    current = corpus_fingerprint([CORPUS])

    altered = tmp_path / "altered.json"
    data = json.loads(CORPUS.read_text(encoding="utf-8"))
    data["urls"] = data["urls"][:-1]
    altered.write_text(json.dumps(data), encoding="utf-8")

    assert corpus_fingerprint([altered]) != current
