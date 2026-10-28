# WebScout MCP - Service Level Objectives (SLO)

## Overview

This document defines the Service Level Objectives (SLOs) for WebScout MCP.
SLOs are measured continuously via Live Network Tests and aggregated into
7-day and 30-day rolling windows.

## SLO Targets

| Metric | 7-Day Target | 30-Day Target | Description |
|--------|-------------|---------------|-------------|
| **Search Success Rate** | ≥ 99.0% | ≥ 98.0% | Percentage of search queries that return valid results |
| **Fetch Success Rate** | ≥ 98.0% | ≥ 97.0% | Percentage of URL fetches that succeed |
| **MCP E2E Success Rate** | ≥ 99.5% | - | MCP protocol end-to-end test success rate |
| **Search P95 Latency** | ≤ 5000ms | - | 95th percentile search response time |
| **Fetch P95 Latency** | ≤ 10000ms | - | 95th percentile fetch response time |
| **Usable Content Rate** | ≥ 85.0% | ≥ 85.0% | Percentage of successful fetches whose returned content is at least `THIN_CONTENT_CHARS` (200) characters |
| **Thin Content Rate** | ≤ 10.0% | ≤ 12.0% | Percentage of fetches returning non-zero content below the thin threshold |
| **Truncation Rate** | *reported, not gated* | - | Percentage of fetches serving a window of a longer page (see below) |

### Why quality metrics exist

Success-rate and latency targets answer "did the request finish", not "did we
get anything worth reading". A 200 response whose body is a captcha, a login
wall, or a JavaScript navigation shell counts as a success under the original
targets, so a content regression is invisible to them.

This is not hypothetical. The v1.9.0 A/B run (2026-10-23, 52 cases) measured a
content-usability deficit of **7.3 percentage points** against a bare baseline
while every success-rate metric stayed green. The three quality targets above
were added so that class of regression shows up in the SLO report instead of
requiring a hand-built A/B harness.

`THIN_CONTENT_CHARS` is deliberately low (200). It counts captcha-only and
navigation-only bodies as thin while leaving short legitimate answers out of
the thin bucket.

#### Truncation is reported, not gated

A fetch is counted as truncated when `has_more=true`, which means the full body
was fetched and extracted and the caller is being served the first window, with
`start_char` available to read on. Nothing was lost.

So `truncation_rate` tracks **how long the pages in the corpus are**, not how
well the service performed. Measured directly: a 577-char page and a 711-char
page never truncate, while a 34603-char page and a 25399-char page always do.

The first real baseline showed the trap:

| Metric | Value |
|---|---|
| usable content rate | 100.0% |
| truncation rate | 70.0% |
| status (before) | **warning** |

Both numbers were correct and the status was not: cross-referencing page length
against window size is arithmetic, not a quality signal. Any documentation-heavy
corpus alerts permanently. The rate now appears under `notes` in the report and
never changes `status`.

### A/B evaluation

The SLO metrics above are absolute: they say how much usable content the service
returns. A/B answers the complementary question — does the pipeline return more
usable content than a plain HTTP GET would?

```bash
# Record a live run, then score it (writes observations + report)
python scripts/ab_evaluate.py --limit 40 --out ab-report

# Re-score recorded evidence offline, no network required
python scripts/ab_evaluate.py --replay ab-report/observations.jsonl --out ab-report/rescore
```

The harness is committed (`webscout_mcp/ab_eval.py`), because its absence is
what made the 2026-10-23 finding unverifiable: that run's harness lived in an
uncommitted directory, so the -7.3pp deficit could never be re-checked. Scoring
is a pure function, the recorded evidence is scalar-only, and the exit code
carries the verdict so CI can gate on it.

Two notes when reading an A/B report:

- **Latency is directional only.** The arms differ in both work scope and
  denominator; each summary records its own `latency_denominator`.
- **A PASS is not a quality statement.** The gates compare the pipeline against
  the baseline, so two equally bad arms pass. The absolute floor is the
  `Usable Content Rate` target above, not this comparison. Reports say so
  explicitly under `advisories` when both arms came back empty.

### The latency gate measures the pipeline, not the network

G3 originally compared P95 ratios only. Ten measured runs showed why that is the
wrong gauge:

| run | pipeline P50 | baseline P50 | delta | ratio |
|---|---|---|---|---|
| 40168930560 | 286ms | 142ms | +144ms | 2.011 |
| 40172773081 | 281ms | 101ms | +179ms | 2.771 |
| 40174846440 | 158ms | 78ms | +80ms | 2.017 |
| 40451391241 | 179ms | 111ms | +68ms | 1.612 |
| 40642421691 | 220ms | 175ms | +45ms | 1.260 |

The pipeline's absolute overhead stayed in a narrow band (+39 to +179ms, median
+80ms) - extraction and classification, the work it exists to do. The ratio
swung 1.26-2.77 solely because the baseline moved between 78ms and 175ms.

A ratio-only gate therefore fires hardest when the network is *fastest*. Six of
ten historical runs failed it while doing identical work.

The gate now passes on either condition:

1. ratio ≤ 1.30 - within bounds outright
2. ratio ≤ 2.00 **and** delta ≤ 300ms - the fixed cost is bounded both ways

The 2.00 ceiling is not slack: without it, a 3x regression on a fast 100ms
baseline is only a +200ms delta and would slip through. 2.00 sits above the
1.626 observed maximum, leaving headroom while still catching a doubling.

With the corrected gate, 9 of 10 historical runs pass and the single failure is
the genuine one (+337ms).

A third note on the gate itself:

- **The usable-rate gate allows one trailing case** (`--case-tolerance`,
  default 1; use 0 for strict). This is not slack for its own sake. A real CI
  run scored 40 cases and found exactly one divergence: a URL where the
  pipeline recorded 0 chars after a 16.9s browser attempt while the baseline
  received 1168 chars for the same URL. Excluding that one transient failure,
  the arms were identical across the other 39. Scoring strictly would have
  reported a -2.50pp regression that did not exist, and a gate that fires on
  one flaky request is a gate people learn to ignore.

  The gate compares **case counts, not percentage points**: with 40 cases one
  case is exactly 2.5pp, so a `-2.5 >= -2.5` comparison is a float-boundary
  trap. The report prints the gap in cases ("pipeline is 1 case(s) behind") so
  the number can be reasoned about directly.

## Metrics Collected

### Search Metrics
- Total searches
- Successful searches
- Success rate (%)
- Fallback count (Bing → DDG/Tavily)
- Fallback rate (%)
- Latency P50 (ms)
- Latency P95 (ms)
- Provider distribution (Bing/DDG/Tavily/SerpAPI)

### Fetch Metrics
- Total fetches
- Successful fetches
- Success rate (%)
- Latency P50 (ms)
- Latency P95 (ms)

### Content Quality Metrics

Emitted by `observability.record_content_quality()` and exposed under
`get_observability_summary()["content_quality"]`:

| Field | Meaning |
|-------|---------|
| `fetches` | Total served fetch results (the denominator) |
| `usable` / `usable_rate` | Returned ≥ 200 chars |
| `thin` / `thin_rate` | Returned 1–199 chars (captcha, nav shell, login wall) |
| `empty` / `empty_rate` | Returned 0 chars |
| `truncated_by_output_limit` / `truncation_rate` | WebScout's own `max_chars` cut a larger body |
| `chars_returned_total` | Sum of returned characters |
| `chars_omitted_total` | Sum of characters available but not served |
| `returned_p50` / `returned_p95` | Percentiles of returned content length |
| `by_backend` / `by_status` | Breakdown by provider and WebResult status |

A provider that raises an exception is recorded as `status="failed"` with zero
characters before the exception propagates, so failures stay in the denominator
and cannot inflate the usable rate.

All fields are scalars. Page content, URLs, headers and credentials are never
accepted by the recorder, so they cannot leak through this path.

### Error Taxonomy
- 403 Forbidden
- 429 Rate Limited
- Timeout
- DNS Failure
- SSL Error
- Connection Reset
- Content Empty
- CAPTCHA
- Other

## SLO Status Levels

| Status | Meaning | Action |
|--------|---------|--------|
| 🟢 **HEALTHY** | All SLO targets met | Normal operation |
| 🟡 **WARNING** | One or more metrics approaching target | Monitor closely, investigate trends |
| 🔴 **VIOLATING** | One or more SLO targets not met | Immediate investigation and remediation |
| ⚪ **NO_DATA** | Insufficient data to calculate SLO | Run live tests to populate metrics |

### NO_DATA is not the same as VIOLATING

Three states are distinguished, and the third used to be reported as the fourth:

| Observations in the window | Rate reported | Status |
|---|---|---|
| none (no reports) | — | `no_data` |
| none (reports present, every counter zero) | `null` | `no_data` |
| some, all failed | `0.0%` | `violating` |
| some, meeting targets | e.g. `100.0%` | `healthy` |

The middle row was the bug. A window full of reports that recorded nothing was
counted as `healthy`, so a pipeline that never actually ran anything presented a
green SLO. Worse, when it was counted at all it produced a success rate of
`0.0%`, which read as a total outage and triggered violations for observations
that did not exist.

Rates are now `null` rather than `0.0` when there are no observations, and a
window with reports but no observations is `no_data` with an explicit note. The
CLI prints `N/A (no data)` and exits 0 for that case: missing data is a gap in
measurement, not a service failure.

## SLO Dashboard

The SLO dashboard is generated automatically after every Live Network Test run:

- **Location**: `slo-reports/SLO_DASHBOARD.md` (in workflow artifacts)
- **JSON**: `slo-reports/slo_report.json`
- **Retention**: 90 days (GitHub Actions artifacts)
- **Update frequency**: Daily (scheduled at 00:00 UTC) + manual triggers

### Dashboard Contents
- Overall SLO status
- 7-day rolling metrics
- 30-day rolling metrics
- SLO violations (if any)
- Search success rate and latency
- Fetch success rate and latency
- Error type breakdown
- Provider distribution

## SLO Aggregation

The SLO aggregator script (`scripts/slo_aggregator.py`) collects historical
live test results and calculates rolling SLO metrics:

```bash
# Run SLO aggregation locally
python scripts/slo_aggregator.py

# Output:
# - slo-reports/slo_report.json (machine-readable)
# - slo-reports/SLO_DASHBOARD.md (human-readable)
```

### Where the aggregator gets its data

The aggregator only reads `live_report.json` files from disk. The content-quality
counters live in process memory, so a run has to write a snapshot or its numbers
never reach a report. Two paths do that:

```bash
# 1. Explicit, deterministic — what the CI live job uses
python -m webscout_mcp metrics snapshot --out live-test-results/live_report.json

# 2. Automatic on shutdown — the MCP server arms this itself
webscout-mcp serve   # writes <cache_dir>/live_report.json on exit

# Inspect counters without writing anything
python -m webscout_mcp metrics show
```

The exit hook is opt-in: library use and the test suite never write snapshots.
A run that recorded nothing produces no file at all, rather than an all-zeroes
snapshot that would be read as "measured, 0% usable".

### How the rolling window actually rolls

A timestamp is what makes "7-day" mean anything, and history is what makes it
have more than one sample. Both were missing:

- **Snapshots now carry `timestamp`** (epoch seconds, matching
  `LiveTestReport.timestamp`). Before this, the aggregator treated every
  snapshot as a legacy report with no date and counted it in *every* window, so
  nothing was ever filtered out - the window covered all history forever.
- **The CI job restores history from the `slo-history` branch.** Each job starts
  from a fresh checkout and artifacts are per-run, so without a durable store the
  window had exactly one sample. The branch is orphaned: CI appends one small
  JSON per run under `runs/<run-id>/live_report.json` and never merges it, which
  keeps monitoring data out of `main` while still being durable.

The nested layout is required, not cosmetic: the loader globs for files literally
named `live_report.json`, so a flat `runs/<id>.json` would be silently invisible
and the history would appear empty.

### Aggregation Logic
1. Load all `live_report.json` files from `live-test-results/` (recursively, so
   restored history under `history/` is included)
2. Filter by date using each report's `timestamp` (7-day and 30-day rolling
   windows)
3. Aggregate metrics across all test runs
4. Calculate percentiles (P50, P95)
5. Compare against SLO targets
6. Generate status (healthy/warning/violating/no_data)
7. Auto-update baseline if metrics improve (ratchet mechanism)

## SLO in Release Gate

SLO metrics are used as part of the release decision process:

- **Stable releases** require 7-day SLO status = HEALTHY
- **Hotfix releases** may proceed with WARNING status if the issue is unrelated
- **No releases** if SLO status = VIOLATING (must fix first)

## SLO Improvement Plan

### Current Baseline (v1.1.x)
- Search success rate: ~99% (measured)
- Fetch success rate: ~98% (measured)
- Search P95 latency: ~300ms (with cache)

### Targets for v1.2+
- [ ] Search success rate: 99.5%
- [ ] Fetch success rate: 99.0%
- [ ] Search P95 latency: < 1000ms (without cache)
- [ ] Add MCP tool-level SLOs (per-tool success rate)
- [ ] Add cross-platform SLOs (Windows/macOS/Linux)
- [ ] Add long-running soak test SLOs (7-day continuous operation)

## Related Documents
- [MODULE_STATUS.md](MODULE_STATUS.md) - Module maturity and stability
- [COMPATIBILITY.md](COMPATIBILITY.md) - MCP 1.x/2.x compatibility
- [SECURITY.md](SECURITY.md) - Security policy and vulnerability reporting
