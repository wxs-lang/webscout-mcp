# Fetch Recovery Policy

## Thresholds

| Name | Value | Unit | Module | Rationale |
|---|---|---|---|---|
| `SHORT_PAGE_TEXT_CHARS` | 2000 | chars | recovery | A genuinely small rendered page is at most this many extracted chars AND must sit on a small HTML document. Both conditions are needed; short text on a large document is a JS shell, not a short page. |
| `THIN_SHELL_TEXT_CHARS` | 1500 | chars | recovery | Below this much extracted text on a script-heavy document, completeness cannot be confirmed even though the strict escalation rule did not fire. |
| `LARGE_HTML_CHARS` | 20000 | chars | recovery | HTML above this size counts as a 'large document' for the shell test. |
| `HIGH_SCRIPT_RATIO` | 0.15 | ratio | recovery | Script bytes / total bytes above this means the page is mostly code, not prose. |
| `MIN_403_HTML_BYTES` | 256 | bytes | recovery | A 403 with at least this much HTML body is treated as a UA-level soft block: the server rejected our client fingerprint but serves real markup to a browser. Below it there is no evidence a browser would help, so we stay conservative. |
| `MIN_TEXT_CHARS_FOR_REAL_PAGE` | 200 | chars | fetch_escalation | Extracted text below this on a non-trivial document is an empty-shell signature. |
| `MIN_HTML_BYTES_FOR_LOW_DENSITY` | 3000 | bytes | fetch_escalation | Low-density escalation requires a non-trivial document. Below this size a page is simply small, and escalating would burn a browser call for nothing. |
| `MIN_PAGE_BYTES_FOR_LOW_QUALITY` | 2000 | bytes | fetch_escalation | The content-quality signal only counts on documents big enough to judge. |
| `LOW_DENSITY_SCRIPT_RATIO` | 0.2 | ratio | fetch_escalation | Script ratio that marks an SPA shell inside the low-density rule. NOT the same decision as HIGH_SCRIPT_RATIO, despite sharing a name: that rule applies above 20000 bytes of HTML with under 1500 chars of text and yields a non-escalating AMBIGUOUS verdict, while this one applies above 3000 bytes with under 200 chars and triggers a browser escalation. Unifying the numbers would change behaviour, so the difference is documented rather than removed. |

## Classification stages (first match wins)

| # | Stage | Condition | Yields |
|---|---|---|---|
| 1 | protocol_terminal_status | HTTP 451 / 401 / 407 / 429 | LEGAL_OR_GEO_BLOCK, AUTH_REQUIRED, RATE_LIMITED |
| 2 | transport_failure | timeout / TLS / DNS / connection / HTTP 5xx | TIMEOUT, TLS_FAILURE, NETWORK_FAILURE, SERVER_ERROR |
| 3 | access_denial | 403 (three sub-cases), 404, robots, other hard errors | SOFT_BLOCK, ACCESS_DENIED |
| 4 | non_html_content | content type in NON_HTML_PREFIXES | UNSUPPORTED_CONTENT_TYPE |
| 5 | output_truncation | metadata.truncated_by_output_limit | OUTPUT_TRUNCATED |
| 6 | browser_signal | should_escalate_to_browser() returns escalate=True | SOFT_BLOCK, JS_REQUIRED, LOW_CONTENT_DENSITY, LOW_QUALITY |
| 7 | success_completeness | body empty / short / dense | AMBIGUOUS, COMPLETE_SHORT_PAGE, COMPLETE_CONTENT |

## Reason to action

| Reason | Action | Confidence | Escalates | Rationale |
|---|---|---|---|---|
| `LEGAL_OR_GEO_BLOCK` | STOP | 0.95 | no | HTTP 451: legally unavailable in this jurisdiction. No client-side action can change it. |
| `AUTH_REQUIRED` | REQUIRE_AUTH | 0.95 | no | HTTP 401/407: the caller must supply credentials. Escalating would only reach the same wall. |
| `RATE_LIMITED` | RETRY_LATER | 0.9 | no | HTTP 429: the host asked us to back off. Retrying immediately makes it worse. |
| `TIMEOUT` | RETRY | 0.85 | no | Transport timeout. The Fetcher already exhausted its own retries before classification. |
| `TLS_FAILURE` | PROVIDER_FALLBACK | 0.85 | no | Certificate/TLS failure: a different provider may have a working trust path. |
| `NETWORK_FAILURE` | RETRY | 0.8 | no | DNS or connection failure: transient by nature, worth one more attempt. |
| `SERVER_ERROR` | RETRY | 0.8 | no | HTTP 5xx: the origin is unhealthy, not our request. |
| `SOFT_BLOCK` | BROWSER | 0.9 | yes | A challenge/captcha page, or a 403 serving real markup to browsers while rejecting our client fingerprint. This is the case a browser can actually fix. |
| `ACCESS_DENIED` | STOP | 0.85 | no | 403 with no challenge, 404, robots denial, or a login wall. A browser would hit the same denial; escalating is pure cost. |
| `UNSUPPORTED_CONTENT_TYPE` | ACCEPT | 0.8 | no | Non-HTML payload (PDF/JSON/XML/image): a dedicated parser handles it, a browser cannot. |
| `OUTPUT_TRUNCATED` | CONTINUE_CONTENT | 0.95 | no | WebScout's own max_chars cut a larger body. The content exists and is already fetched; the fix is to serve the next window, never to open Chromium. |
| `JS_REQUIRED` | BROWSER | 0.85 | yes | Page renders nothing without client-side JS, so a real browser is the only way in. |
| `LOW_CONTENT_DENSITY` | BROWSER | 0.8 | yes | Classic SPA shell: very little text on a non-trivial, script-heavy document. |
| `LOW_QUALITY` | BROWSER | 0.6 | yes | The content-quality analyzer flagged the page. Lowest confidence of the browser reasons, because the analyzer is a heuristic over already-extracted text. |
| `AMBIGUOUS` | NONE | 0.4 | no | HTTP success, no extractable content, no browser signal. Evidence is insufficient, so we prefer a non-answer over a speculative browser call. |
| `COMPLETE_SHORT_PAGE` | ACCEPT | 0.7 | no | Genuinely short page: small text on a small document. Nothing more to get. |
| `COMPLETE_CONTENT` | ACCEPT | 0.9 | no | Content is present and dense enough. Accept as-is. |

## Browser escalation signals

| Signal | Condition | Reason | Confidence |
|---|---|---|---|
| non_html | content type in NON_HTML_PREFIXES | NOT_ESCALATED | 0.0 |
| challenge_on_any_status | CHALLENGE_MARKERS present | SOFT_BLOCK | 0.9 |
| challenge_on_200 | CHALLENGE_MARKERS present in a 200 body | SOFT_BLOCK | 0.95 |
| js_placeholder_on_200 | JS_PLACEHOLDER_MARKERS present in a 200 body | JS_REQUIRED | 0.85 |
| low_density | text < MIN_TEXT_CHARS_FOR_REAL_PAGE AND html > MIN_HTML_BYTES_FOR_LOW_DENSITY AND (script_ratio > LOW_DENSITY_SCRIPT_RATIO OR js placeholder) | LOW_CONTENT_DENSITY | 0.8 |
| low_quality | metadata.content_quality == 'low' AND html > MIN_PAGE_BYTES_FOR_LOW_QUALITY | LOW_QUALITY | 0.6 |

## Marker sets

| Set | Count | Purpose |
|---|---|---|
| `CHALLENGE_MARKERS` | 8 | Detect an interstitial challenge page where a browser could plausibly pass. |
| `JS_PLACEHOLDER_MARKERS` | 5 | Detect a page that renders nothing without client-side JS. |
| `LOGIN_WALL_MARKERS` | 13 | Detect a genuine authentication requirement. A browser cannot bypass a real login, so this must NOT escalate - escalating here wastes a browser call and still fails. Includes Chinese markers because the target sites are not all English. |
| `NON_HTML_PREFIXES` | 6 | Content types that dedicated parsers handle. Escalating to a browser for these would be wrong. NOTE: this tuple is currently defined twice - once in recovery and once in fetch_escalation. |

## Structural findings

- two distinct script-ratio gates: recovery thin_shell uses 0.15 (html>20000, text<1500, does NOT escalate), escalation low_density uses 0.2 (html>3000, text<200, DOES escalate). Different decisions; do not unify blindly.
