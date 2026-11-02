# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## v2.2.0 (2026-11-02)

Both changes are about making what is watched stable, and the defects fixed along the way
share one shape: each made `web_monitor` report "no change" for a reason that had nothing
to do with the page itself.

### Added

- **`json_path` on `web_monitor`** - watch one value inside a JSON response instead of the
  whole body. Two selector languages, chosen by prefix on the expression:

  ```
  json:$.product.price      JSONPath
  jq:.product.price         jq
  $.product.price           bare form, treated as JSONPath
  ```

  The design follows changedetection.io: a prefix picks the language, and the selection is
  reduced to a string so the ordinary diff applies. `jqraw:` was deliberately not adopted -
  its purpose there is to suppress JSON quoting, which this project does not do, so it would
  be a keyword with no behaviour behind it.

  Reducing to one field is the point: neighbours and formatting churn while the watched
  value does not. Measured on a local endpoint, a change to `name` and `stock` produced zero
  changes when watching `$.product.price`, and the price move itself produced one.

- **`[json]` extra** carrying `jsonpath` and `jq`, also included in `[all]`. Both optional
  because `jq` needs a native build. Asking for a language that is not installed returns the
  install command rather than an `ImportError`. Verified in two environments: a default
  install (JSONPath works, `jq:` names the extra) and a venv with `[json]` installed.

### Fixed

- **`web_monitor` now routes through `fetch_service`.** It previously let the monitor do its
  own HTTP, so it got no TLS impersonation, no browser escalation and no recovery
  classification. The practical consequence: monitoring a page that needs either reported
  "no change" forever, because the fetch itself never succeeded - indistinguishable from a
  page that genuinely did not change. A new `monitor_adapter` bridges the async pipeline into
  the monitor's synchronous fetcher protocol. Measured through the real pipeline:
  `recovery_outcome="browser_success"`, i.e. escalation actually engaged.

- **A cached body made monitoring useless.** Measured against a local endpoint that changed
  between requests:

  ```
  call 1  set=100  got '{"price": 100}'   cached=False
  call 2  set=900  got '{"price": 100}'   cached=True      WRONG
  with bypass_cache=True: call 2 got '{"price": 900}'
  ```

  A monitor reading a cached body compares a page with its own cached copy and can never see
  a change. Both the JSON probe and the adapter now bypass the cache.

- **A malformed JSONPath silently watched the whole document.** The `jsonpath` library does
  not raise on bad syntax; it degrades it into a wildcard:

  ```
  '$[['      -> 10 matches, first is the whole document
  '$..*'     ->  9 matches, first is NOT the document   (legitimate)
  '$.product'->  1 match                                (legitimate)
  ```

  A typo would have recorded a huge unstable string as the watched value. The measurable
  signature - the document appearing first in a multi-match result - is now rejected with a
  message naming the problem. An earlier attempt bounded matches by node count; that did not
  fire, because 10 matches on a 20-node document is not out of range.

- **The response never said what was watched.** `payload_selected` was computed and dropped,
  so a wrong selector was indistinguishable from a page that never changes. The response now
  echoes `json_path` and `selected_value`.

- **`generate_docs.py` wrote CRLF**, so a one-line change to `docs/tools.md` appeared as a
  917-line diff. All three writes now pin `newline="\n"`, with a `.gitattributes` as the
  second half of that guarantee.

### Compatibility

**15 tools, unchanged in count and schema.** `json_path` is a new optional parameter that
defaults to empty, so existing calls behave identically. `COMPATIBILITY.md` records it along
with the two behaviours a caller must know: the `[json]` extra is needed for either
selector language, and a malformed JSONPath is refused rather than silently widened.

### Verified

- 26 tests for the selector module on a default install, the same suite with `jq` present
  (where the two jq tests run instead of skipping), and 87 across the selector, adapter,
  persistence, change-detection and alert-target suites
- end to end against a local JSON endpoint: baseline, price change detected, unrelated field
  changes ignored, missing path reported, unavailable language named
- ruff, format and generated docs clean

### Known gaps

- Scheduling remains the caller's responsibility; `web_monitor` checks once per call.
- Change screenshots are still not implemented. They need a browser and are a separate cost
  from detection.

## v2.1.0 (2026-11-02)

### Added

- **`web_monitor`** - check a URL for changes since the last check. Reports text changes,
  price moves and keyword appearances; filters noise through `ignore_text` and
  `ignore_selector`; pushes findings to one or more targets through `notify`.
  15th tool, marked beta.

  **It checks once per call and does not schedule itself.** That is stated in the tool
  description because a user who configures it once and expects automatic tracking would
  otherwise reasonably conclude the feature is broken. The first call for a URL records a
  baseline and reports nothing, signalled by `baseline_established: true`.

- **`ignore_text` / `ignore_selector` on the monitor** - the two filters that make
  monitoring usable. Without them any page carrying a timestamp, session id or rotating
  ad reports a change on every check.

### Fixed

Three defects stood between the existing monitor code and it working. Each one hid the
next, which is worth recording:

- **The comparison baseline was never persisted.** `_save_history` stored only the change
  log, and `check_url` called it only inside `if changes:`. The first check for a URL -
  which by definition reports nothing - therefore wrote nothing, so every process started
  with an empty baseline and could never report a change at all. Measured through the
  tool: the second call, after a price moved from 100 to 900, returned 0 changes and no
  state file existed.

  Fixed twice over, because the first fix alone was not enough: `_last_content` is stored
  under a `__baseline__` key, *and* the save happens whenever the baseline moved rather
  than only when something was reported.

- **Notifications could never fire.** `_send_alerts` built `monitor.AlertMessage` and
  handed it to a channel, whose `format_message` reads `message.level`. But
  `alert_channels.AlertMessage` is a *different* dataclass: `level` instead of
  `change_type`, float instead of ISO timestamp. Every send raised, was caught by a
  per-channel `try/except`, and logged. Converted at the boundary, and - more importantly
  - the per-send result is now **returned** instead of discarded, because a swallowed
  exception is indistinguishable from success when nobody sees the outcome.

- **`webhook://` always rebuilt as `https`.** Only visible once delivery results were
  surfaced: the first real attempt failed in seconds with `SSL: WRONG_VERSION_NUMBER`, so
  every local or internal http endpoint was unreachable. Loopback hosts now default to
  http, others to https, and `?http=1` forces plain http for a public host.

- Also: `open()` without an encoding in both history functions (cp936 on Windows would
  corrupt non-ASCII content), and a state file written before `__baseline__` existed now
  loads as "no baseline" rather than raising.

### Changed

- `web_monitor`'s price comparison is independent of `min_change_size`. A one-character
  move like `$100.00` -> `$900.00` is exactly what a text-size threshold swallows, so
  with `price_selector` set the comparison is a percentage against
  `price_change_threshold`.
- The monitor's `min_change_size` now measures characters that actually differ rather
  than `abs(len(new) - len(old))`. The old measure reported 0 for any same-length rewrite,
  including every price change of equal digit count.

### Compatibility

**15 tools.** The fourteen from v2.0.0 keep their names, parameters and response shapes;
`web_monitor` is additive. `COMPATIBILITY.md` records it as beta with its two behavioural
caveats (no self-scheduling; first call is a baseline).

### Verified

- 24 new tests, one per defect plus the end-to-end delivery path
- delivered against a real local HTTP server: change detected -> `{"channel":"webhook",
  "success":true,"message":"HTTP 200"}` and a payload containing the new price
- a bad target is reported in `notifications.errors` while the good one still fires
- credentials embedded in a target URL never appear in the response

### Known gaps

- `web_monitor` uses the monitor's own fetcher, not `fetch_service`, so it gets no TLS
  impersonation or browser escalation yet. Stated in the tool description rather than
  left for a user to discover.
- Scheduling is the caller's responsibility; there is no built-in interval runner.

## v2.0.0 (2026-11-01)

The v2 line begins the "AI / RAG / Knowledge Graph" scope from `REFACTOR_PLAN.md`. For
the first time the tool surface does more than retrieve content - it understands it.

### Compatibility: what actually changed

**11 tools became 14.** All eleven existing tools keep their names, parameters and
response shapes; the three new ones are additive. But three capabilities that existed
in `extras/` and were reachable by import now behave differently, and their outputs are
numbers a caller may have stored:

| Surface | Change | Why it counts as breaking |
|---|---|---|
| `content_quality` / `web_compare_sites` scores | readability only contributes once a page has 100+ words | **scores for very short pages are lower than in v1.x** |
| `rag_optimizer` retrieval ranking | stop-word filtering + IDF, sentence-aligned chunks | a stored result set will not match a fresh one |
| `competitor_analyzer.ComparisonResult.to_dict()` | now includes `comparison_matrix` | additive, but the dict has a new key |

If you compare v1.x metrics against v2.0.0, expect lower content scores on thin pages
and different retrieval orderings. Both were wrong before.

### Added

Three tools, each marked **beta** in `COMPATIBILITY.md` with its limits stated in the
tool description and in its own response `notes` - so a caller does not need to read
documentation to learn what it cannot do.

- **`web_knowledge_graph`** - entities and relationships from a page or text, with
  centrality ranking. Relationships are proximity-based and always
  `co_occurs_with`; entity types come from patterns, and a word the patterns cannot
  classify is `unknown` rather than guessed.
- **`web_rag_context`** - the passages most relevant to a query, compressed to fit a
  context window. Lexical IDF ranking, not embeddings, so synonyms do not match.
- **`web_compare_sites`** - SEO, performance, content and link comparison across 1-10
  sites, with a per-metric matrix and prioritised recommendations. A URL that cannot be
  fetched appears in `failures` rather than aborting the comparison.

### Fixed

Each of these was measured before and after; the before-numbers are in the section for
the release that fixed them, and every fix has a test that fails if the number regresses.

- **`rag_optimizer` did not retrieve.** Five probe queries, answer present in the
  retrieved top-2: **0 of 5**. Every query returned the same first chunk. Four causes: a
  scoring formula that spent its budget on stop words, chunk heads severed mid-sentence
  by the overlap, long paragraphs never split, and compression emitting the same
  sentence twice. Now **5 of 5** at top-1.
- **`competitor_analyzer` gave identical scores to everything.** A 667-word article and
  a 6-word stub both scored 63.5. Four causes: `compare_sites` read keys
  `seo`/`performance`/`content`/`links` while callers passed `*_metrics`; the SEO field
  names it expects are emitted by nothing; readability worth 35 points inverted the
  ranking for thin pages; and `to_dict` dropped the comparison matrix it had computed.
  Now 86.0 versus 67.0 with the right winner.
- **`knowledge_graph` split entities and mislabelled types.** The technology pass
  registered `tech_python` alongside an existing `python`, producing one node linked to
  itself; and every single capitalised word defaulted to `person`, so Python, Django and
  Transformer were people. Split nodes and self-edges are now zero, and unclassifiable
  words are `unknown`.
- **Script bodies could survive tag stripping.** `</script >` and `</script\t\n bar>` are
  valid HTML end tags that a bare `</script>` pattern misses, letting script text reach
  the text metrics and inflate the content score of a page with little real content.
  Caught by CodeQL.

### Changed

- `docs/RECOVERY_POLICY.md` is generated from the policy table and checked in CI rather
  than hand-written; it had drifted to 17 rules and 8 markers against 18 and 11.
- `web_fetch`'s response now carries `recovery_reason`, `recovery_action` and
  `recovery_outcome`, so a challenge page - which returns 200 with no error - is
  distinguishable from a successful fetch.
- Challenge detection recognises non-English interstitials and scans the extracted body,
  not only the first 4KB of HTML where the marker may not appear.
- `extras/seo_metrics.py` added: the SEO field set `competitor_analyzer` expects, which
  no existing analyzer emitted.

### Known gaps

Unchanged from v1.x, and restated because v2.0.0 does not address them:

- Sites that block by IP reputation (stackoverflow, zhihu, amazon, reddit) still return
  403/202 even through a browser. A residential proxy is the remedy; no client-side
  change is.
- The three new tools are **rule-based, not model-based**. They need no API key, which is
  why they work out of the box, and it is also why their output is coarser than a model
  would produce. The response `notes` say so in each case.
- `web_monitor` (from the v2 scope) is not included. It needs persisted state and a time
  dimension, and where that state lives is a design decision not yet made.

## v1.14.0 (2026-11-01)

### Fixed

- **A challenge page was indistinguishable from a successful fetch.** Reported as a
  200 with no error, and it reached that state through four separate gaps:

  | Layer | Problem |
  |---|---|
  | marker set | eight markers, all English/Cloudflare - a Chinese interstitial matched none |
  | scan window | `html[:4096]` only; the marker sat at byte 25065 of a 25258-byte page |
  | reason name | reused `SOFT_BLOCK`, which means "rejected silently", not "told to wait" |
  | payload | the decision existed only in `route_trace`, invisible to an MCP caller |

  Each is fixed: three measured Chinese markers added, the extracted body is scanned
  as well as the HTML head, `CHALLENGE` is its own reason, and the payload now
  reports it.

  The scan-window fix matters most. `_looks_like_challenge` read the first 4KB, which
  on the real page was `<head>` boilerplate and inline CSS. The extracted body is 58
  characters with the marker at position 0. Measured against two legitimate short
  pages, checking the body produced no false positives; scanning all 25KB would have
  matched any large page whose scripts mention "captcha".

### Added

- **`recovery_reason` / `recovery_action` / `recovery_outcome` in the payload.** Three
  additive scalars, present only when a decision was made. Before this, a caller
  received:

  ```json
  {"status_code": 200, "error": null, "error_code": null, "extraction_status": "ok"}
  ```

  and had no way to know the pipeline had concluded "CHALLENGE, a browser is needed,
  none is registered". `browser_attempted` could not convey it: that field is set only
  when a browser ran, so its absence conflates "not needed" with "not installed" -
  which need different remedies.

  `recovery_outcome` is the one that separates:

  | value | meaning | remedy |
  |---|---|---|
  | `browser_unavailable:fallback_unavailable` | no backend registered | install `[browser]` |
  | `browser_success` | escalated and worked | nothing |
  | `browser_failed:...` | escalated, site rejected | network/IP, not code |

- **A troubleshooting section in README** covering what a challenge page looks like,
  the two commands that enable escalation, the honest boundary of what a browser does
  not fix, proxy configuration, and how to read `route_trace`. `README_zh.md` got a
  short pointer. Every command in it was executed before committing.

### Compatibility

**11 MCP tools, unchanged.** No parameter was removed or renamed. Three additive
response fields, following the same precedent as v1.10.0's `error_code` / `retryable`
/ `extraction_status` and v1.4.0's `status` / `error`.

### Changed

- `docs/RECOVERY_POLICY.md` is now generated from the policy table and checked in CI
  rather than hand-written. It had drifted to 17 rules and 8 markers against 18 and 11
  in code while `--check` reported everything up to date. The CI `git diff` guard now
  covers it.
- The lint job installs the project instead of individual packages. Naming a package
  per CI failure was guesswork; the import chain is
  `recovery_policy -> fetch_escalation -> fetch_provider -> search -> search_health ->
  serpapi_backend`.
- `generate_docs.py` no longer crashes on a console whose default codec is not UTF-8
  (`UnicodeEncodeError: 'gbk' codec can't encode character '\u2705'`), found by
  running it in a clean venv instead of a configured shell.
- `test_snapshot_on_exit.py` no longer leaves a `somewhere.json` in the working
  directory: the exit hook was armed with a relative path and stayed armed
  process-wide.

## v1.13.0 (2026-11-01)

### Fixed

- **Brotli responses were served as raw bytes.** The browser fingerprint advertised
  `Accept-Encoding: gzip, deflate, br`, but `pyproject.toml` never declared the
  `brotli` package. httpx only decodes brotli when it is installed, and it fails
  silently when it is not: status 200, `content-encoding: br`, and the compressed
  bytes decoded as text. Measured on example.com in an environment without brotli:

  | request headers | result |
  |---|---|
  | fingerprint (`gzip, deflate, br`) | 311 chars, readable ratio 0.412 |
  | without `Accept-Encoding` | 577 chars, readable ratio 1.000 |

  This is present from the initial commit (2026-08-28), so for any default install
  every brotli-compressed page has been mojibake. Extraction then ran over that
  mojibake and reported `extraction_status: "ok"`, because it had produced text.

  **Effect on the numbers you may have been reading:** the content-usability SLO was
  counting mojibake as usable content. v1.12.0 and earlier dashboards are not
  comparable to v1.13.0 ones; the new figures are lower and correct.

  Fixed at the source: the fingerprint no longer emits `Accept-Encoding`, and httpx
  negotiates it, adding `br` only when it can decode it.

### Added

- **`content_grading`** grades extracted text by shape: `usable`, `thin`, `empty`,
  or `garbled`. `garbled` is what surfaced the defect above - 145 replacement
  characters were previously indistinguishable from content. The rule is layered
  because no single feature separates real prose from page chrome:

  | sample | chars | avg sentence | truth |
  |---|---|---|---|
  | example.com | 279 | 92.3 | useful - short but real sentences |
  | news.ycombinator | 4136 | 7.8 | useful - long, link list |
  | medium.com | 149 | 7.4 | useless - fragments |
  | thepaper.cn | 253 | 8.2 | useless - fragments |

  Sentence length alone rejects hackernews; length alone accepts thepaper, so the
  rule takes both plus a script-aware floor (CJK expresses the same content in fewer
  characters, and an English-calibrated threshold rejected legitimate Chinese
  sentences averaging 19).

- The SLO counters now carry a `content_grade` label and the aggregator reports a
  `garbled_rate` alongside the existing rates.

### Compatibility

**11 MCP tools, unchanged.** `webscout_mcp.content_quality` remains the
compatibility shim for the website-analysis module; the new grader lives at
`webscout_mcp.content_grading`. No parameter was removed or renamed.

### Measured after the fix

Ten pages, graded by the new module:

```
usable  7   iana.org, wikipedia, docs.python, mozilla, hackernews, reuters
thin    0
empty   3   example.com (156 chars), medium.com (149), 36kr (58)
garbled 0
usable_rate 70.0%
```

reuters now yields 2844 characters of article text through TLS impersonation, which
it could not do before this release.

## v1.12.0 (2026-11-01)

### Added

- **TLS fingerprint impersonation** (`curl_cffi`), tried before escalating to a
  browser. The blocking signal is often the TLS handshake rather than the
  rendering: reuters returned 401 to a plain client and 403 to headless Chromium,
  then 200 with a full article when the handshake matched Safari - in 955ms rather
  than a 3-6s browser launch. Applies to a 401/403 response and to TLS/trust-store
  failures; a 200 never triggers it.
- **Profile rotation.** Which fingerprint works is target-dependent, measured
  rather than assumed: reddit returns 166KB to `chrome131` and 8KB to
  `safari17_0`; reuters returns 1.3MB to `safari17_0` and 774 bytes to
  `chrome131`. Profiles are tried in order until one succeeds.

### Fixed

- **A broken system trust store no longer fails the whole fetch.** When every
  `httpx` request fails with `CERTIFICATE_VERIFY_FAILED` - which is what a
  TLS-rewriting corporate proxy produces - the fetch now falls back to
  `curl_cffi`, which carries its own CA bundle and TLS stack.
- **libcurl could not read a CA bundle under a non-ASCII path** (curl error 77,
  e.g. an install under `D:\测试\...`). The bundle is now staged to an ASCII
  location. The failure previously surfaced as an apparent network error.

### Compatibility

**11 MCP tools, unchanged.** No parameter was removed or renamed. Impersonation
adds a retry path; the shape of a failed response is identical to before when it
cannot help.

### Known gaps

`curl_cffi` and the local browser are both opt-in through the `[browser]` extra.
With it installed, real-world usability over the 16-site probe is 10/16. The
remaining six are not addressable by fingerprint work:

| Site | Response to every profile tried | What would be needed |
|---|---|---|
| medium.com | 200, but 149 chars of navigation | JS rendering (SPA) |
| stackoverflow.com | 403 | residential IP |
| zhihu.com | 403 | residential IP, login session |
| amazon.com | 202 | JS + cookie handshake |
| reddit.com | 200, humanity challenge | residential IP |
| bbc.com | connect failure | - |

A proxy can be configured for the browser (`BrowserConfig.proxy_server`); nothing
in this release changes the IP reputation, which is the binding constraint on
those sites.

## v1.11.0 (2026-10-29)

Measured against sixteen real-world sites rather than the ten curated live-test
URLs, which report 100% success and say nothing about pages with cookie walls,
anti-bot checks or client-side rendering.

### Added

- **Browser escalation works without Docker.** `BrowserFetcher` was implemented
  but never referenced, and could not have run: it uses playwright's synchronous
  API inside an asyncio codebase. It now runs in a single-worker executor and is
  registered as the BROWSER fallback when no Crawl4AI sidecar is configured.
  `web_fetch` can escalate to a real browser after `pip install
  'webscout-mcp[browser]'` and `playwright install chromium`.
- Real-world usability measured end to end, with results recorded below.

### Fixed

- **Recovery treated unextractable HTML as article text.** `classify_recovery`
  branched on `len(content)` without consulting `extracted`, so a JS shell
  returned "the article is longer, fetch the next window" and a 2KB bot-check page
  returned "content complete, accept". A body we could not extract is now detected
  and routed to the browser-signal path.
- **Extraction could report success with nothing to show.** The readability branch
  returned `("", "ok")` for a bare `<div id="root">`, producing a payload that
  claimed `extraction_status: "ok"` while `extracted` was False and raw HTML was
  served.
- **The browser advertised itself as HeadlessChrome.** The UA said Chrome/120
  while `Sec-Ch-Ua` said `"Chromium";v="148", "HeadlessChrome";v="148"` - two
  contradiction signals for any Client-Hints-aware bot check. UA and hints are now
  derived from the engine's real version and agree.

### Compatibility

**11 MCP tools, unchanged.** No parameter was removed or renamed. The only
behavioural change is that a page whose content cannot be extracted is now
described as content-poor instead of complete - which is what B2 in `GOAL.md`
already specified.

### Known gaps

Real-world usability went from 8/16 to 9/16. The remaining failures are
anti-bot walls, and they are not fixed by this release:

| Site | Response | What would be needed |
|---|---|---|
| medium.com | 403 | residential IP, TLS fingerprint |
| stackoverflow.com | 403 | residential IP |
| zhihu.com | 403 | residential IP, login session |
| reuters.com | 401 | login session |

Client Hints are now consistent, which removes two red flags - but Cloudflare-grade
walls weigh IP reputation, TLS fingerprint and request history, none of which a
headless Chromium on a datacenter or proxied IP can change. A proxy can be
configured (`BrowserConfig.proxy_server`), and that is the lever available today.

## v1.10.0 (2026-10-29)

Twenty-nine changes since v1.9.1, grouped by what a user would notice.

### Added

- **`web_fetch` now explains failures.** Responses carry `error_code`
  (`FETCH_NOT_FOUND`, `FETCH_SERVER_ERROR`, `FETCH_CONNECTION_ERROR`, ...) and
  `retryable`. Previously a 404 arrived as `{"status_code": 404, "error": null}`
  and a DNS failure as `"Failed after 3 retries: "` - the status was there but
  nothing said what it meant or whether retrying was worth anything. Both fields
  are additive.
- **`extraction_status`** (`ok` / `empty` / `unavailable`) says why text was not
  extracted. `extracted: false` alone could not distinguish a broken environment
  from a page with no article, and in the `unavailable` case callers were
  receiving raw HTML after asking for markdown.
- **Recovery policy is inspectable as data** (`recovery_policy.py`): 9 thresholds,
  17 reason rules, 7 stages, 6 escalation signals, rendered to
  `docs/RECOVERY_POLICY.md`.
- **A reproducible A/B harness** (`scripts/ab_evaluate.py`) comparing the pipeline
  against a bare-HTTP baseline over a curated corpus, with per-arm observations
  committed as JSONL so verdicts can be replayed.
- **Content usability is measurable** and the rolling SLO window rolls: 7d/30d
  metrics, persisted counters, snapshots on shutdown and from CI.
- **Install smoke test in CI**: builds a wheel, installs it into a clean venv, runs
  the console script and compares its version against the git tag.
- **Promotion evidence check** (`scripts/check_promotion_evidence.py`): reports how
  many days of live-test data back each Stable rating.

### Fixed

- **4xx was reported as a retryable server error.** Every unlisted 4xx (400, 402,
  405, 409, 418, ...) fell through to `FETCH_SERVER_ERROR`, which is in the
  retryable set, so `StructuredError` promoted `retryable` to true - telling
  callers to retry a malformed request. Now classified by status class; a
  non-HTTP status (0, 1xx, >=600) is `SYSTEM_ERROR` rather than a fabricated 5xx.
- **404 was mapped to the generic `FETCH_FAILED`** while `FETCH_NOT_FOUND` existed
  and `recovery.py` branched on it - a branch unreachable from a real 404.
- **Empty retry messages**: `str(httpx.ConnectError(...))` can be empty, so the
  error read `"Failed after 3 retries: "`. Now falls back to the exception type.
- **The A/B latency gate measured the network, not the pipeline.** Across ten runs
  the pipeline's overhead was a stable +39 to +179ms while the p95 ratio swung
  1.26-2.77 solely because the baseline moved 78-175ms; a ratio-only gate fires
  hardest when the network is fastest. Now passes on a bounded ratio or a bounded
  absolute delta. Historical pass rate 6/10 -> 9/10.
- **An unreliable corpus host** (neverssl.com, 8/8 direct attempts failed) was the
  sole cause of the 2.10 latency ratio. Replaced rather than deleted, so the
  corpus keeps its 60-entry contract.
- **Truncation was treated as a quality failure.** `truncated_by_output_limit`
  means the caller received window 1 of N with a continuation offset, not that
  content was lost. Demoted to an informational note.
- **SLO reporting**: no longer prints `None%` when there is no data, separates
  "no observations" from "every observation failed", and stops overwriting the
  live report with an empty snapshot.
- **Quality was double-counted** on the fetch path; recorded exactly once now.
- **`is_available` on the browser backend meant "configured"**, not reachable, so
  the preflight reported a sidecar as usable when it was not.
- **One transient case could flip an A/B verdict**; a single-case tolerance was
  added.

### Changed

- **Five-layer reorganisation started.** `errors`, `utils`, `cache` and `config`
  now live in `webscout_mcp/core/`, with deprecation shims at the old paths. The
  error taxonomy moved first because dependency analysis showed zero internal
  dependencies and ten dependents.
- `content_quality` and `broken_link_checker` implementations moved to `extras/`;
  both tools remain registered and callable.
- Recovery policy constants named and de-duplicated.
- 68 merged branches cleared; stale checkboxes corrected.

### Security

- **`broken_links` hardened against SSRF**: every link destination is validated,
  each hop goes through a pinned-IP transport, blocked targets are reported
  explicitly instead of as ordinary broken links, with deterministic regression
  coverage for loopback and private-address redirects.

### Compatibility

**11 MCP tools, unchanged.** No parameter was removed or renamed. The three new
response fields are additive: consumers that ignore them behave exactly as before,
and tests assert every pre-existing key survives. See `COMPATIBILITY.md`.

### Known gaps

- Nine tools are declared Stable, but live-test history began 2026-10-25, so the
  30-day bar in `REFACTOR_PLAN.md` is not yet met. Measured, not hidden - see the
  promotion evidence step in the live-tests workflow.
- The five-layer reorganisation is 4/5 through `core/`; `services`, `providers`,
  `security`, `observability` and `server` are not started.

## v1.9.1 (2026-10-24)

### HTTP 403 recovery fix
- **403 responses now classified into recoverable vs terminal**: a 403 with an HTML body ≥256 bytes (UA-level soft block) escalates to BROWSER. Previously every non-challenge 403 was `ACCESS_DENIED`/STOP, so 403 soft blocks on baike.baidu.com and dictionary.cambridge.org never reached the browser escalation path (observed in the v1.9.0 A/B evaluation: Arm A body availability 7.3pp below the direct baseline).
- **Bounded alternate-FETCH fallback**: when a browser-recoverable soft block has no browser backend wired in, exactly ONE alternate FETCH provider is attempted (never recursive, never re-classified). Recovered content is surfaced through the legacy output path with `fallback_used` / `fallback_provider` markers.
- **Login-wall guard**: explicit authentication demands (EN/ZH) keep a 403 terminal — a browser cannot bypass credentials, so escalation is suppressed.
- **Non-HTML 403 stays terminal**: JSON/API risk-control bodies (e.g. zhihu's `40362` endpoint) are not misclassified as browser-recoverable.
- **Tests**: 19 new deterministic offline regression tests (classification, bounded escalation, browser-failure preserves structured 403, alternate-provider fallback, no loop, 200 fast path untouched). Also fixes the A/B evaluation scaffold `truncated_html` NameError (scaffold-only, not a production defect).
- **MCP schema unchanged**: **11 MCP tools total**.

## v1.9.0 (2026-10-08)

### search_health: Beta → Stable
- **Fixed P0: unobserved no longer defaults to healthy**: `BackendHealth.get_health_score()` now returns `None` when `total_requests == 0`, instead of `1.0`. `get_status()` returns `"unobserved"` for backends with no request history. `SearchHealthManager.get_health_report()` reports `unobserved_backends` count and `overall_health_score=None` when nothing has been observed. Unknown must not be reported as healthy.
- **Explicit circuit breaker state machine**: `circuit_state` field with values `closed` → `open` → `half-open` → `closed`. Backward-compatible `circuit_open` property returns True for both open and half-open states.
- **Strict half-open probe concurrency**: `half_open_max_requests` is now actually enforced via `acquire_half_open_slot()` / `release_half_open_slot()`. `can_use()` returns False when half-open slots are exhausted. `half_open_success_threshold` controls how many successful probes close the circuit.
- **Monotonic clock for interval calculations**: Internal circuit recovery timing uses `time.monotonic()` via `circuit_open_monotonic`, immune to system clock changes. Wall-clock `circuit_open_time` retained for external reporting.
- **Result classification**: Added `record_timeout()`, `record_invalid_query()`, `record_circuit_skipped()`, `record_unavailable()`. Invalid queries do NOT pollute provider health (no request count, no failure count, no circuit impact). Circuit skips and unavailable states are counted but do not mutate health.
- **Observability**: Added `recent_failures` deque (max 10), `circuit_open_count`, `circuit_recovery_count`, `last_recovery_time`, per-category counters (`total_empty`, `total_timeouts`, `total_invalid_queries`, `total_circuit_skips`, `total_unavailable`).
- **Health query has no side effects**: `get_health_report()` and `to_dict()` do not mutate backend state.
- **JSON backward compatibility**: All original v1.8.0 fields preserved (`name`, `enabled`, `status`, `health_score`, `total_requests`, `total_successes`, `total_failures`, `consecutive_failures`, `consecutive_successes`, `circuit_open`, `last_failure_reason`, `last_failure_time`, `last_success_time`, `failure_threshold`, `recovery_time`). New fields added additively.
- **MCP schema unchanged**: `search_health()` signature preserved. **11 MCP tools total**.

## v1.8.0 (2026-10-08)

### metadata_extract: Beta → Stable
- **Fixed P0 interface mismatch**: `MetadataExtractor.extract()` now accepts optional `base_url` keyword argument, resolving `TypeError` when called from MCP `metadata_extract` tool as `extract(html, base_url=url)`. When provided, overrides constructor base_url.
- **SSRF safety on metadata path**: Dedicated `metadata_fetcher` instance with `safety_check_enabled=True` enforces SSRF checks on the initial URL and every redirect hop via httpx `event_hooks` request hook. Shared `fetcher` keeps default (safety off) so `web_fetch` behavior is unchanged. Private IPs, localhost, metadata endpoints blocked.
- **Final URL base resolution**: Relative URLs (og:image, favicon, canonical, twitter:image, images, links) now resolved against `result.final_url` (post-redirect) instead of original request URL.
- **article:* dual-attribute support**: `article:author`, `article:published_time`, `article:modified_time`, `article:section`, `article:tag` now extracted from both `name` AND `property` attributes (previously only `name`).
- **JSON-LD @graph expansion**: Schema.org `@graph` arrays are now recursively flattened into individual nodes via `_flatten_json_ld()`, bounded by `MAX_JSON_LD_DEPTH=3`. Outer graph dict preserved.
- **Hard output limits**: `MAX_RAW_META_TAGS=200`, `MAX_JSON_LD_ENTRIES=50`, `MAX_IMAGES=100`, `MAX_LINKS=200` prevent memory exhaustion on large pages.
- **Malformed JSON-LD handling**: Invalid JSON-LD scripts are skipped with debug logging (no crash, no silent empty success).
- **MCP schema unchanged**: `metadata_extract(url)` signature preserved. **11 MCP tools total**.

## v1.7.0 (2026-10-08)

### rss_parse: Beta → Stable
- **Fixed P0 interface mismatch**: `fetch_and_parse_feed()` now accepts `max_entries` parameter (was causing `TypeError` when called from MCP `rss_parse` tool). `max_entries` is clamped to [1, 100] and slicing is enforced.
- **SSRF safety on RSS path**: Initial URL and every redirect hop are validated via `check_url_safe()`. Private IPs, localhost, metadata endpoints, and non-http(s) schemes are blocked. Uses httpx `event_hooks` request hook pattern (same as fetcher/crawler).
- **Hard resource limits**: `max_redirects=5`, `max_body_bytes=5MB`, per-request timeout. Streaming download with size enforcement prevents memory exhaustion.
- **XML external entity (XXE) protection**: Uses `lxml-xml` parser which disables external entity resolution by default. XXE payloads cannot leak file contents.
- **Feed auto-discovery**: When URL returns HTML, `link rel="alternate"` tags with `application/rss+xml` / `application/atom+xml` types are discovered. Up to 5 candidates, each SSRF-validated. No infinite recursion.
- **Parsing reliability**: Added RSS 1.0 (RDF) support; `content:encoded` works with or without namespace declaration; relative URLs resolved against final URL; UTF-8 BOM and ISO-8859-1 encoding handled; empty/malformed/non-feed content raises `RSSParseError` (fail-closed, not silent empty).
- **MCP schema unchanged**: `rss_parse(url, max_entries=20)` signature preserved. 11 MCP tools total.

## v1.6.0 (2026-10-07)

### web_crawl: Beta → Stable
- Fixed cross-host redirect robots compliance: robots.txt is now checked
  BEFORE requesting the target host's body, not after. Redirect hops are
  handled manually in the crawler with per-hop SSRF + robots validation.
- Added manual redirect handling in crawler (follow_redirects=False on
  crawl path; general web_fetch behavior unchanged).
- MCP schema unchanged.

## [Unreleased]

### Added
- **Unified Decision Dataset & Replay** (v1.5.0 Phase 1): `DecisionEvent` records sanitized Fetch + Search production decisions (reason, action, outcome, latency, request/outcome features) to a local SQLite store.
- **`DecisionStore`**: SQLite with WAL, 30-day retention, 256 MB size cap, idempotent schema migration, and best-effort fault isolation (store failures never affect production).
- **`ReplayCase`** + offline `decision_evaluator`: deterministic fixture cases with `label_source` (deterministic_fixture / human_verified / objective_outcome / historical_verified; `jev_verified` explicitly rejected).
- **Decision CLI**: `decision-report`, `decision-export`, `decision-replay`, `decision-label` (CLI only, not MCP tools).
- **Fetch + Search adapters**: `record_fetch_decision()` / `record_search_decision()` hook into production paths; 0 routing changes.
- **Privacy**: URLs stored as scheme + host + canonical hash only; search queries stored as hash + length; `_scrub_dict` removes Authorization / Cookie / token / api_key / password / credential at store layer.
- **Telemetry toggle**: `WEBSCOUT_DECISION_TELEMETRY=0` disables recording; `WEBSCOUT_DECISION_DB` overrides store path.
- **Objective Decision Evaluation** (v1.5.0 Phase 2): `objective_labeler.py` + `advisor_evaluator.py` for offline Jev-vs-deterministic comparison; `run_objective_evaluation.py` CLI harness with preflight/live/report-only modes; Browser counterfactual runner for needs_escalation ground truth; run_id-scoped `join_report()`; ReplayCase gains `run_id`/`trace_id`/`position`; `jev_eligible` vs `jev_enabled` semantics; Search result_relevant position-level join.

### Evaluation Results (Phase 2 Final Closure)
- **needs_escalation**: NO AUTHORITY. Jev FPR=95.7% (22/23 false positives on NO cases); 4 YES cases found in 165 Browser CF evaluations (insufficient for recall estimation).
- **result_usable**: HOLD / NO PROVEN VALUE. Accuracy 56.8% vs majority baseline 52.3% (+4.5pp) on n=44, but recall=9.5%.
- **result_relevant**: RESEARCH VALUE ONLY. Accuracy 26% on 100 all-positive sample (worse than majority baseline 100%); negative ground truth never completed.
- **Correlation health**: 100% join coverage, 598 valid Jev predictions, 0 errors, TypeSafe real provider.
- **Decision**: Jev does NOT enter production routing. Phase 3 paused. Infrastructure preserved but frozen. See `docs/PHASE2_CLOSURE.md`.

### Changed
- No production routing changes. Fetch (v1.3.0) and Search (v1.4.0) recovery behavior unchanged.
- MCP tools remain 11. Jev remains pure Shadow / optional.

## [1.4.0] - 2026-09-23

Self-healing search core. No new MCP tools (still 11); `web_search` signature unchanged; response gains additive `status` / `error` fields.

### Added
- **Search SUCCESS / EMPTY / ERROR semantics**: EMPTY is a legitimate provider outcome (no results, no transport error) and no longer counts as a hard failure or opens a circuit.
- **Search cache identity correctness**: cache key now includes `casefold(query)`, `max_results`, `safe_search`, `region`, `language`, `country`; different `safe_search` / `country` / `region` / `language` / `max_results` never share a cache entry.
- **`SearchFailureKind`** (TIMEOUT / RATE_LIMITED / AUTH / PARSER / NETWORK / SERVER / CONFIG / PROVIDER / INVALID_REQUEST) as internal typed failure taxonomy.
- **`SearchRecoveryDecision`** (`SearchRecoveryReason` / `SearchRecoveryAction`) with deterministic classifier and finalizer.
- **Deterministic search recovery**: every provider outcome maps to ACCEPT / TRY_NEXT_PROVIDER / RETURN_EMPTY / RETURN_ERROR / STOP / NONE.
- **Unified search recovery orchestration**: `SearchService.search()` is fully decision-driven; `SearchRecoveryDecision` is the single source of truth. Each provider is called at most once per request; no same-provider retry.
- **SearchHealthManager as sole SEARCH circuit availability authority**; ProviderRouter owns ranking/latency/error metrics only.
- **Legacy request-level double-search cutover**: when `SearchService` is initialized, `web_search` never falls back to the legacy `SearchEngine` per request (SUCCESS / EMPTY / ERROR / STOP / unexpected-exception all stay in SearchService). Legacy remains a startup-only fallback.
- **`web_search` additive response fields**: `status` (`success` / `empty` / `error`) and `error` (only on error). `query` / `count` / `results` unchanged.
- **`recovery_execution` observability**: per-action outcome counts.
- **Empty / whitespace query validation**: rejected at the SearchService entry with `SEARCH_INVALID_QUERY`, 0 provider network / health / circuit / Jev calls.

### Changed
- Tavily / SearXNG / legacy HTML backends now emit typed `StandardErrorCode` + `SearchFailureKind` instead of bare strings (fixes `SearchResponse.to_dict()` crash on string `error_type`).
- SearchService timeout now emits `SEARCH_TIMEOUT` (was incorrectly `FETCH_TIMEOUT`).
- Legacy Bing/DDG/Google/Brave parser-zero-results now raise `SearchParseError` → `PARSER_FAILURE` (not EMPTY).
- `fallback_reasons` only records reasons that actually caused a provider switch; `RESULT_AVAILABLE` / ACCEPT / STOP are excluded.
- A single request-level STOP is recorded exactly once (no duplicate recovery/execution counts).

### Security
- Search route traces and error responses never include API keys, Authorization, Cookie, or credential-bearing headers.
- SSRF guards, metadata sanitizer, and v1.3.0 Fetch Core behavior unchanged.

## [1.3.0] - 2026-09-21

Self-healing fetch core. No new MCP tools (still 11); `web_fetch` gains one backwards-compatible parameter.

### Added
- **Progressive content delivery / continuation**: after one fetch, long articles are delivered in `max_chars` windows; the response includes an additive `continuation` block. Re-call `web_fetch(url, start_char=continuation.next_start_char)` to read the next window — follow-up windows are served from a local content snapshot with **0 extra HTTP / extraction / Jev / Browser** calls.
- **Deterministic recovery classification** (`RecoveryReason` / `RecoveryAction`) and **unified recovery orchestration**: one `RecoveryDecision` drives ACCEPT / CONTINUE_CONTENT / BROWSER (max one) / RETRY (delegated) / RETRY_LATER / PROVIDER_FALLBACK (max one) / REQUIRE_AUTH / STOP / NONE.
- **Content sufficiency / truncation semantics**: explicit `pre_limit_content_chars`, `returned_content_chars`, `truncated_by_output_limit`, `omitted_chars`; `max_chars` now means the returned window, not a hard fetch cap; output truncation no longer triggers Browser escalation.
- **Jev shadow evaluator (optional)**: `pip install "webscout-mcp[jev]"`. Disabled by default, BYOK, pure shadow (never changes production routing); schema v2 with `run_id` / `trace_id` / `jev_call_id` and call-level token/latency accounting.

### Changed
- Unified `WebResult`, metadata sanitization, canonical URL identity, SSRF hardening, provider registry/router, and observability.
- `typesafe-sdk` moved from core dependencies to the optional `jev` extra (and `all`); core install no longer requires it.
- Cache key now includes the effective output limit (avoids cross-`max_chars` cache pollution).
- Docs aligned: README reports the real 11 tools; `web_fetch` uses `max_chars` + `start_char` (legacy `max_length` removed).

### Security
- SSRF guard unchanged across fast fetch, browser fallback, provider fallback, and continuation; metadata sanitizer strips authorization/cookie/token/credential fields.

## [1.0.0] - 2026-09-06

### 🎉 First Stable Release

After extensive development, testing, and real-world validation, webscout-mcp reaches v1.0.0 stable.

### ✨ Key Features
- **11 stable MCP tools** for web research
- **Dynamic provider routing** with health-based scoring
- **Multi-backend search** with automatic failover (Bing → DuckDuckGo → Tavily)
- **Circuit breaker** per provider with automatic recovery
- **Startup self-check** for reliability verification
- **Comprehensive test suite** (unit, integration, MCP E2E, fault injection, live)
- **Full CI/CD** with quality gates and automated releases
- **Cross-platform support** (Linux, macOS, Windows)
- **Stability contract** with frozen APIs and error codes

### 📦 Installation
```bash
pip install webscout-mcp==1.0.0
```

### 🚀 Quick Start
```bash
# Start MCP server
python -m webscout_mcp serve

# Verify installation
python scripts/verify_installation.py
```

### 🔧 MCP Tools (11)
- `web_search` - Search with automatic fallback
- `web_fetch` - Fetch and extract page content
- `web_crawl` - Crawl websites with depth limits
- `web_extract` - Extract structured data via CSS selectors
- `cache_stats` - View cache statistics
- `cache_clear` - Clear cache
- `search_health` - Provider health and dynamic routing status
- `metadata_extract` - Extract page metadata
- `rss_parse` - Parse RSS/Atom feeds
- `content_quality` - Analyze content quality
- `broken_links` - Check for broken links

### 📚 Documentation
- [README.md](README.md) - Full documentation
- [COMPATIBILITY.md](COMPATIBILITY.md) - Stability contract and frozen APIs
- [SECURITY.md](SECURITY.md) - Security policy
- [CONTRIBUTING.md](CONTRIBUTING.md) - Contributing guide

---

## [0.9.0] - 2026-09-06

### ✨ Added
- **COMPATIBILITY.md** - Formal stability contract documenting frozen APIs
  - 11 MCP tools with frozen names, schemas, and return structures
  - 40+ standard error codes
  - 30+ environment variables with stable names
  - Deprecation policy (2 minor version warning period)
  - Semantic versioning commitment
- **Cross-platform verification script** (`scripts/verify_installation.py`)
  - 12 checks covering imports, server creation, SearchService, config, errors
  - Platform detection (Linux/macOS/Windows)
  - Exit code 0 for all pass, 1 for failures
- **Platform support matrix**: Linux (Ubuntu/Debian/CentOS), macOS 11+ (Intel/Apple Silicon), Windows 10+
- **Python support**: 3.10, 3.11, 3.12

### 🔧 Changed
- API/configuration freeze point for v1.0.0 stability
- All interfaces documented and frozen for backwards compatibility

---

## [0.8.1] - 2026-09-06

### ✨ Added
- **Expanded live E2E test scenarios** from 15 to 20 search queries
  - English technical (5): python, github, postgresql, fastapi, docker
  - English news (3): tech news, python release, open source ai
  - English github (2): mcp server example, fastapi repo
  - Chinese technical (5): corresponding Chinese queries
  - Chinese news (3): tech news, AI trends, open source software
  - Chinese general (2): exam books, grad school math
- **Expanded fetch URLs** from 5 to 10
  - Technical docs (5)
  - News sites (2): Hacker News, Python blog
  - GitHub repo (1): fastapi
  - Redirect page (1): httpbin
  - JS-heavy page (1): python.org
- **Categorized reporting** in live test results
  - `search_by_category`: success rate and latency per query category
  - `fetch_by_category`: success rate and latency per URL category
  - Enables long-term tracking of scenario-specific stability

---

## [0.8.0] - 2026-09-06

### ✨ Added
- **Dynamic Provider Router** (`provider_router.py`)
  - Replaces fixed-order fallback with intelligent health-based selection
  - ProviderHealthScorer calculates 0-100 score per provider
  - Weighted scoring: success rate (40%), latency (25%), error rate (20%), circuit state (15%)
  - Rolling 24h metrics window with P50/P95 latency tracking
  - Error type taxonomy: 429, 403, timeout, connection, other
- **Cost-aware routing**
  - ProviderCostTier: FREE, LOW_COST, PAID, PREMIUM
  - `prefer_free` mode: free providers get small score boost when scores are close
  - Paid providers (Tavily) only used when free providers are degraded
- **Provider metrics tracking**
  - Rolling request/success/error history (1000 entries)
  - P50/P95 latency calculation
  - Error type breakdown
  - Circuit state tracking (open/half-open/closed)
- **Enhanced health report** in `search_health` tool
  - `dynamic_routing` section with ranked providers
  - Per-provider scores, success rates, latencies, cost tiers
  - Detailed reasons for each score

### 🔧 Changed
- SearchService now uses dynamic routing by default
- Tavily provider integrated as PAID tier fallback
- Bing/DuckDuckGo as FREE tier primary providers

---

## [0.7.1] - 2026-09-06

### 🔧 Fixed
- **Ruff G201**: Use `log.exception()` instead of `log.error(..., exc_info=True)` in tavily_provider.py
- **Lint cleanup**: Fixed F541 (f-string without placeholders) in examples/ and tests/
- **All GitHub Actions** updated to latest versions (checkout@v4, setup-python@v5, upload-artifact@v4)

### ✨ Added
- Code Quality workflow now fully green (Ruff, Mypy, Bandit, CodeQL all pass)

---

## [0.7.0] - 2026-09-06

### ✨ Added
- **Startup Self-Check** (`startup_check.py`)
  - 5 checks run at MCP server startup: cache, search_engine, search_service, fetcher, search_connectivity
  - Runs in background (non-blocking, does not delay server start)
  - Each check tracks duration, pass/fail status, and detailed message
  - Startup report included in `search_health` tool response
- **Tavily Search API Provider** (`tavily_provider.py`)
  - Stable API-based search designed specifically for AI agents
  - No HTML scraping, no DOM/CAPTCHA/Bot detection risk
  - Auto-detects `TAVILY_API_KEY` environment variable
  - Full error handling: 401, 429, 5xx, timeout, connection error
  - Integrated as 3rd fallback in SearchService (Bing → DuckDuckGo → Tavily)
  - Circuit breaker and health tracking work automatically
- **New config options**: `TAVILY_API_KEY`, `TAVILY_TIMEOUT`

### 🔧 Changed
- SearchService fallback chain: Bing → DuckDuckGo → Tavily (when API key configured)
- Free providers remain primary, paid Tavily only used when needed

---

## [0.6.0] - 2026-09-02

### ⚠️ BREAKING CHANGES
- MCP server startup command changed from `python -m webscout_mcp.server` to `python -m webscout_mcp serve`
- Experimental features (RAG, Knowledge Graph, AI Optimizer, SEO, OCR, PDF, Monitor, etc.) moved to `extras/` directory

### ✨ Added
- **5 new MCP tools** (total 11):
  - `search_health` - Get health report for all search backends (circuit breaker status)
  - `metadata_extract` - Extract page metadata (JSON-LD, OpenGraph, Twitter Cards)
  - `rss_parse` - Parse RSS/Atom feeds and return entries
  - `content_quality` - Analyze content quality (readability, keyword density, structure)
  - `broken_links` - Check for broken links on a web page

- **New Search Architecture**:
  - `SearchService` + `SearchProvider` standardized interface
  - Search backends: Bing HTML, DuckDuckGo HTML, SerpAPI (optional)
  - Automatic failover between search backends
  - Circuit breaker per backend (OPEN/HALF_OPEN/CLOSED states)
  - Provider health monitoring and statistics

- **Comprehensive Test Suite**:
  - Unit tests (100+ tests)
  - Integration tests
  - MCP protocol-level E2E tests (deterministic, required CI)
  - MCP Live E2E tests (real network, scheduled)
  - System-level fault injection tests
  - Live Network Tests (scheduled daily, 15 searches + 5 fetches)
  - Coverage reporting

- **CI/CD Infrastructure**:
  - Python 3.10 / 3.11 / 3.12 test matrix
  - Ruff linting (enforced)
  - Mypy type checking (enforced)
  - Bandit security scanning (enforced for medium/high severity)
  - CodeQL security analysis
  - Docker image build and publish
  - Automated Release Gate (waits for all required checks)
  - Main branch protection with required status checks

- **Error Handling**:
  - Standardized error hierarchy (30+ error classes)
  - Structured error responses: `{code, provider, retryable, message}`
  - Error codes: FETCH_TIMEOUT, FETCH_FORBIDDEN, FETCH_RATE_LIMITED, SEARCH_BACKEND_FAILED, etc.

- **Observability**:
  - Project-owned structured logger (no global logging pollution)
  - Search health reporting with fallback rate, error rate, provider circuit status
  - Live test metrics: success rate, P50/P95 latency, fallback rate, error type breakdown
  - DDG fallback detailed metrics tracking

- **Security**:
  - SSRF protection
  - URL validation
  - Sensitive data filtering
  - robots.txt respect
  - SECURITY.md policy document

### 🔧 Changed
- `web_search` now uses new `SearchService` by default, falls back to old `SearchEngine`
- `search_health` now reports active `SearchService` status instead of old `SearchEngine`
- MCP E2E tests split into deterministic (required CI) and live (scheduled) layers
- Experimental features moved to `extras/` directory for physical isolation
- Documentation auto-generated from MCP tool registry (single source of truth)
- Coverage threshold management with baseline ratchet approach

### 🐛 Fixed
- MCP Live E2E server startup command (was `python -m webscout_mcp.server`, now `python -m webscout_mcp serve`)
- Global `logging.setLoggerClass()` pollution of host Python process
- F821 undefined-name lint exemptions removed
- `cache_clear()` logging TypeError with standard Python logger
- AsyncClient event loop lifecycle issue (recreate client on loop change)
- ConcurrencyLimiter semaphore/event loop deadlock causing 10-minute CI timeout
- Live Test pytest exit code being swallowed by `tee` (added `set -o pipefail`)
- Live Report direct push to protected main branch (now uses artifacts only)
- Circuit breaker half-open failure not resetting recovery timer
- SerpAPI region/locale handling (wt-wt → proper language/country codes)
- MODULE_STATUS.md tool count drift (now auto-generated)

### 📚 Documentation
- README.md with badges, quick start, tool reference, configuration
- MODULE_STATUS.md (auto-generated from tool registry)
- SECURITY.md with vulnerability reporting policy
- CODE_OF_CONDUCT.md
- Issue templates (Bug Report, Feature Request)
- PR template
- CONTRIBUTING.md

## [Unreleased]

### Added
- **Core Infrastructure Optimization**
  - Unified error hierarchy with 30+ specialized error classes
  - Comprehensive security module (SSRF protection, input validation, rate limiting, sensitive data filtering)
  - Async utilities (retry, concurrency limiter, circuit breaker, performance monitoring)
  - Architecture module (event bus, dependency injection, middleware pipeline, command pattern)
  - Health check module (liveness/readiness probes, system monitoring, dependency checks)

- **Core Function Deep Optimization**
  - Search optimizer (concurrent search, smart caching, intelligent ranking, query understanding)
  - Content extractor (multi-algorithm fusion, quality assessment, language detection)
  - RAG optimizer (semantic chunking, context compression, query rewriting)
  - Browser optimizer (instance pooling, human behavior simulation)
  - AI optimizer (prompt engineering, output validation, hallucination detection)

- **Extended Feature Modules**
  - SimHash near-duplicate detection
  - Hybrid search RAG optimization
  - Pydantic configuration models
  - PDF document processing
  - Data cleaning pipeline
  - Competitor analysis
  - Knowledge graph construction
  - Prometheus metrics monitoring
  - Browser fingerprint enhancement
  - REST API server
  - OCR engine
  - Multi-language translator
  - Multi-channel alerting

- **Test System**
  - Integration test framework (8 module interaction test suites)
  - Performance benchmark tests (9 module performance tests with statistics)
  - Enhanced conftest.py with custom markers and fixtures
  - 884+ total test cases (unit + integration + performance)

- **Deployment & Operations**
  - Optimized Dockerfile (multi-stage build, health check, non-root user)
  - Enhanced docker-compose.yml (Redis service, resource limits, security options)
  - Enhanced .dockerignore
  - Health check endpoints for container orchestration

- **Documentation**
  - Comprehensive CHANGELOG.md
  - CONTRIBUTING.md with contribution guidelines
  - docs/ directory with usage guides and best practices
  - Enhanced README.md with detailed documentation

### Changed
- Improved error handling consistency across all modules
- Enhanced security validation for all external inputs
- Optimized performance of core search and extraction operations
- Improved documentation and code comments

### Fixed
- Various bug fixes and stability improvements
- Fixed edge cases in content extraction and parsing
- Improved error recovery and retry logic

## [0.4.0] - 2024-08-28

### Added
- Initial public release
- Web search with multiple backends (Bing, DuckDuckGo)
- Web content fetching and extraction
- Web crawling with concurrency control
- AI content processing (summarization, classification, sentiment analysis)
- Vector store and semantic search
- Headless browser automation
- SEO analysis and broken link checking
- Website monitoring
- Data export (multiple formats)
- RSS feed parsing
- Plugin system
- Configuration management
- Logging system
- Caching system
- Rate limiting
- MCP server support (stdio and SSE transport)

## [0.3.0] - 2024-08-20

### Added
- Enhanced search result ranking
- Improved content extraction algorithms
- Added more AI processing capabilities
- Enhanced vector search performance
- Added browser fingerprinting support
- Improved error handling and retry logic

### Changed
- Refactored core modules for better maintainability
- Improved configuration management
- Enhanced logging and monitoring

### Fixed
- Fixed various bugs in web crawling
- Fixed content extraction edge cases
- Improved stability of headless browser operations

## [0.2.0] - 2024-08-10

### Added
- Added plugin system for extensibility
- Added data export in multiple formats
- Added RSS feed parsing
- Enhanced SEO analysis capabilities
- Added website monitoring features
- Improved documentation

### Changed
- Improved performance of search operations
- Enhanced content extraction quality
- Refactored configuration system

### Fixed
- Fixed memory leaks in long-running crawls
- Fixed race conditions in concurrent operations
- Improved error recovery

## [0.1.0] - 2024-08-01

### Added
- Initial alpha release
- Basic web search functionality
- Basic web content fetching
- Basic web crawling
- Basic AI content processing
- Basic vector store
- Basic headless browser support
- MCP server basic support

---

## Upgrade Guide

### From 0.3.x to 0.4.0

1. **Configuration Changes**
   - New configuration options available for security, rate limiting, and caching
   - Review the updated configuration documentation for new options

2. **API Changes**
   - Error handling has been unified - update error catching code
   - New health check endpoints available
   - Enhanced search and extraction APIs

3. **Dependencies**
   - New optional dependencies for OCR, translation, and API server
   - Install with `pip install webscout-mcp[all]` for all features

4. **Deployment**
   - New Docker image with health check support
   - Updated docker-compose.yml with Redis support
   - Review the deployment documentation for new options

---

## Versioning

This project uses [Semantic Versioning](https://semver.org/):

- **MAJOR** version: Incompatible API changes
- **MINOR** version: New functionality in a backwards-compatible manner
- **PATCH** version: Backwards-compatible bug fixes

---

## Contributing

Please read [CONTRIBUTING.md](CONTRIBUTING.md) for details on our code of conduct and the process for submitting pull requests.

---

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
