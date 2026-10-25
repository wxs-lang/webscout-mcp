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
| **Truncation Rate** | ≤ 25.0% | - | Percentage of fetches where WebScout's own output limit cut the content |

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

### Aggregation Logic
1. Load all `live_report.json` files from `live-test-results/`
2. Filter by date (7-day and 30-day rolling windows)
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
