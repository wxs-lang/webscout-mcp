# v1.5.0 Phase 2 — Objective Decision Evaluation: Final Closure Report

> **Status**: FROZEN / CLOSED  
> **Date**: 2026-10-07  
> **Decision**: Jev does NOT enter production routing. Phase 3 paused.

---

## 1. Executive Summary

After Phase 1 (Decision Data Infrastructure) and Phase 2 (Objective Decision Evaluation), the Jev TypeSafe shadow evaluator has been rigorously evaluated against deterministic recovery rules on real production traffic.

**Final verdict: Jev does not demonstrate sufficient value to warrant production authority in any of the three evaluated questions.**

| Question | Verdict | Reason |
|---|---|---|
| `needs_escalation` | **NO AUTHORITY** | Severe over-escalation: FPR=95.7% on 23 NO cases; 0 true positive samples |
| `result_usable` | **HOLD / NO PROVEN VALUE** | Accuracy 56.8% vs majority baseline 52.3% (+4.5pp), but recall=9.5%; sample too small and imbalanced |
| `result_relevant` | **RESEARCH VALUE ONLY** | Accuracy 26% on 100 all-positive sample (worse than majority baseline 100%); negative ground truth never completed |

---

## 2. Phase 2 Execution Summary

### 2.1 Real Evaluation Runs

| Run ID | Description | Key Metrics |
|---|---|---|
| `objective-v150-p2-real-002` | Stage A — Full corpus live evaluation | 598 valid Jev predictions, 0 errors, correlation coverage=1.0 |
| `objective-v150-p2-real-003` | Stage B/C — Class-balance strengthening | 140 human labels (later invalidated and re-collected), 165 Browser CF cases |

### 2.2 Environment

- **Jev provider**: TypeSafe (real, not fake/noop)
- **Model**: `jev-1.13.0` (requested `jev-latest`)
- **SDK**: `typesafe-sdk 0.6.0`
- **JEV_ENABLED**: true
- **JEV_PROVIDER**: typesafe
- **Mode**: pure Shadow (0 production routing changes)

### 2.3 Correlation Health

- `advisor_enabled_decisions`: 127
- `joined`: 127
- `unexpected_unjoined`: 0
- `operation_join_coverage`: 1.0
- `jev_records_total`: 598
- `jev_valid_predictions`: 598
- `jev_error_records`: 0
- `jev_valid_rate`: 100%

---

## 3. Question-by-Question Results

### 3.1 needs_escalation (browser escalation warranted?)

**Ground truth**: 23 objective cases, ALL NO (browser_escalation_not_warranted).  
**Jev performance**: TP=0, TN=1, FP=22, FN=0  
**False Positive Rate**: 95.7% (22/23)  
**Deterministic rule**: 23/23 correct (always NO on these cases)

**Stage C Browser CF expansion** (165 unique URLs, frozen objective criteria):
- YES (browser_escalation_warranted): **4**
- NO (browser_escalation_not_warranted): 85
- AMBIGUOUS: 76 (24 browser not observed + 35 primary_failed_browser_minimal + 17 low_primary_no_material_gain)

**YES cases**:
1. `angular.io/guide/architecture` — primary 1268 chars, browser 34702 chars
2. `angular.io/docs` — primary 1268 chars, browser 34450 chars
3. `leafletjs.com/SlavaUkraini/` — primary error, browser 8336 chars
4. `medium.com/tag/javascript` — primary error, browser 27566 chars

**Conclusion**: Jev severely over-escalates. On cases where browser escalation is NOT warranted, Jev says YES 95.7% of the time. The 4 YES cases found in Stage C are insufficient to evaluate recall (positive class). **Jev must NOT receive escalation authority.**

### 3.2 result_usable

**Ground truth**: 44 human-verified cases (21 positive / 23 negative)  
**Jev performance**:
- Accuracy: 56.8% (25/44)
- Majority baseline: 52.3% (23/44, predict negative)
- Gain: +4.5 percentage points
- Recall: 9.5% (2/21)
- Precision: 66.7% (2/3)
- Specificity: 100% (23/23)

**Conclusion**: Jev shows marginal accuracy gain over majority baseline but has extremely low recall (misses 90.5% of usable content). The sample is small (n=44) and the gain is not statistically compelling. **HOLD — no proven production value.**

### 3.3 result_relevant

**Ground truth**: 100 human-verified cases, ALL positive (relevant).  
**Jev performance**:
- Accuracy: 26% (26/100)
- Majority baseline: 100% (predict positive)
- Jev is **74 percentage points WORSE** than majority baseline

**Stage C negative candidate pack**: 60 candidates generated using lexical/entity mismatch heuristic (enriched for likely-negative), but **human labeling was never completed**.

**Conclusion**: On an all-positive sample, Jev incorrectly labels 74% of results as not relevant. Negative ground truth was never completed, so balanced evaluation is impossible. **Research value only — do not enter production.**

---

## 4. Methodology & Limitations

### 4.1 What Was Done Right
- Real TypeSafe Jev (not fake/noop), 598 predictions, 0 errors
- Production FetchService/SearchService wiring (not simulated decisions)
- run_id/trace_id correlation with 100% join coverage
- Privacy-preserving Decision DB (URL/query hashes only, no raw content)
- Objective labeler for needs_escalation (browser counterfactual evidence)
- Human-verified labels for result_usable (44) and result_relevant (100)
- Frozen evaluation criteria (no threshold tuning to favor Jev)

### 4.2 Limitations
1. **needs_escalation positive class underrepresented**: Only 4 YES cases found in 165 Browser CF evaluations. True recall cannot be reliably estimated.
2. **result_relevant negative class missing**: Stage C 60 negative candidates were never human-labeled. All-positive sample makes accuracy meaningless.
3. **result_usable small sample**: n=44 is too small for statistically significant conclusions.
4. **Case-control enriched sampling**: Stage C Search candidates were heuristically enriched for negatives, so raw accuracy/prevalence estimates do not reflect production distribution.
5. **Single model version**: Only `jev-1.13.0` was evaluated. Newer versions may perform differently.
6. **No latency/cost analysis**: Phase 2 focused on accuracy; production latency and cost per call were not benchmarked.

---

## 5. Infrastructure Preservation

The following Jev-related infrastructure is **preserved but frozen** (no further expansion):

| Component | Status |
|---|---|
| Jev TypeSafe client (`jev_client.py`) | Preserved, pure Shadow |
| JevStore (SQLite) | Preserved |
| DecisionEvent ↔ Jev correlation (run_id/trace_id) | Preserved |
| join_report() with run-scoping | Preserved |
| Objective labeler (`objective_labeler.py`) | Preserved |
| Advisor evaluator (`advisor_evaluator.py`) | Preserved |
| Evaluation harness (`run_objective_evaluation.py`) | Preserved |
| Browser counterfactual runner | Preserved (evaluation-only) |
| ReplayCase with run_id/trace_id/position | Preserved |
| `jev_eligible` / `jev_enabled` metadata | Preserved |
| Decision CLI (`decision-report`, etc.) | Preserved |

**Do NOT delete any of the above.** They may be useful for future re-evaluation with newer Jev model versions.

---

## 6. Phase 3 Decision

**Phase 3 (Jev Advisory Shadow Validation) is PAUSED.**

Entry criteria (not met):
- [ ] needs_escalation: sufficient YES+NO ground truth with balanced evaluation
- [ ] result_usable: statistically significant gain over baseline (n>44)
- [ ] result_relevant: balanced positive+negative ground truth with balanced accuracy
- [ ] Jev demonstrates stable gain over simple baseline in at least one question
- [ ] Latency/cost analysis completed
- [ ] Production safety review passed

**Do not implement Phase 3 until all criteria are met.**

---

## 7. Next Steps

Return to WebScout main product roadmap. Recommended priorities (in order):

1. **Stabilize Beta tools**: `web_crawl`, `search_health`, `metadata_extract`, `rss_parse` — promote from Beta to Stable with additional testing and edge-case hardening.
2. **Promote Experimental tools**: `content_quality`, `broken_links` — evaluate readiness for Beta promotion.
3. **Core performance**: Profile and optimize `web_fetch` / `web_search` p95/p99 latency.
4. **Provider expansion**: Add more search/fetch providers (SerpAPI, Brave, etc.) to improve redundancy.
5. **Documentation**: Complete tutorials and usage guide for all 11 tools.

Jev re-evaluation may be revisited in the future with:
- Newer Jev model versions
- Larger balanced ground truth datasets
- Latency/cost benchmarking
- But **not as the immediate next priority**.

---

## 8. Artifacts

| Artifact | Location |
|---|---|
| Stage A report | `.webscout-eval/objective-v150-p2-real-002/objective-eval-report.json` |
| Stage B/C report | `.webscout-eval/.webscout-eval/objective-v150-p2-real-003/objective-eval-report.json` |
| Browser CF analysis | `.webscout-eval/objective-v150-p2-real-003/browser-cf-combined-analysis.jsonl` |
| Browser CF summary | `.webscout-eval/objective-v150-p2-real-003/browser-cf-objective-summary.json` |
| Search negative candidates | `.webscout-eval/.webscout-eval/objective-v150-p2-real-003/StageC_Search_Negative_Candidates.xlsx` |
| Decision DB | `.webscout-eval/.webscout-eval/objective-v150-p2-real-003/decision.db` |
| Jev DB | `.webscout-eval/.webscout-eval/objective-v150-p2-real-003/jev.db` |

---

*This document is the authoritative Phase 2 closure record. No further Phase 2.x experiments should be conducted without explicit approval.*
