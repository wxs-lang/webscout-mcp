"""A human-verification page must be recognised as a challenge, not as thin content.

## Measured

reddit.com returns, after browser escalation, a 240-char page:

    "Prove your humanity
     We're committed to safety and security. But not for bots.
     Complete the challenge below and let us know you're a real person."

None of the 11 existing challenge markers matched - they cover Cloudflare-specific strings
(`just a moment`, `cf-browser-verification`) and two Chinese phrases, but no generic
"verify you are a person" wording. So the page was classified `LOW_CONTENT_DENSITY`.

## What this changes and what it does not

The classification becomes `CHALLENGE`, which is more accurate: `LOW_CONTENT_DENSITY` tells
a caller the page was thin, while `CHALLENGE` tells them it is a bot wall. That label reaches
`route_trace` and the legacy output.

It does **not** change the verdict - reddit stays `degraded`, because a challenge page is
still not content. The value is in the diagnosis, and these tests pin exactly that, so the
claims stay proportionate.
"""

from __future__ import annotations

import pytest

from webscout_mcp.fetch_escalation import _CHALLENGE_MARKERS
from webscout_mcp.fetch_provider import FetchResponse
from webscout_mcp.recovery import RecoveryAction, RecoveryReason, _looks_like_challenge, classify_recovery

REDDIT_CHALLENGE = (
    "Prove your humanity\n\nWe're committed to safety and security. But not for bots. "
    "Complete the challenge below and let us know you're a real person. "
    "Reddit, Inc. © 2026. All rights reserved."
)


def test_reddit_challenge_page_is_recognised():
    """The exact page that was previously treated as ordinary thin content."""
    assert _looks_like_challenge(REDDIT_CHALLENGE), (
        "the human-verification wording must be recognised; it was not before"
    )


@pytest.mark.parametrize(
    "phrase",
    [
        "prove your humanity",
        "not for bots",
        "complete the challenge",
        "verify you are human",
        "human verification",
        "人机验证",
        "滑动验证",
    ],
)
def test_each_added_marker_stands_alone(phrase):
    """One phrase is enough; they are alternatives, not a combined signature."""
    assert _looks_like_challenge(f"<html><body>{phrase}</body></html>")


def test_a_200_challenge_is_classified_as_challenge():
    """Better diagnosis: CHALLENGE, not LOW_CONTENT_DENSITY."""
    r = FetchResponse(
        url="https://www.reddit.com/",
        final_url="https://www.reddit.com/",
        status_code=200,
        provider="browser",
        content=REDDIT_CHALLENGE,
        content_type="text/html",
        raw_html="<html><body>" + REDDIT_CHALLENGE + "</body></html>",
        extracted=True,
        extraction_status="ok",
    )
    decision = classify_recovery(r)
    assert decision.reason is RecoveryReason.CHALLENGE, f"expected CHALLENGE, got {decision.reason}"
    assert decision.action is RecoveryAction.BROWSER


def test_article_prose_is_not_mistaken_for_a_challenge():
    """The added phrases must not fire on ordinary text about security topics."""
    article = (
        "Security teams often discuss how to verify a user is human without adding "
        "friction. A real person should not have to solve a puzzle to read the news. " * 20
    )
    assert not _looks_like_challenge(article), "prose *about* verification must not be treated as a verification page"


def test_marker_list_has_no_duplicates():
    """A duplicate would silently change the count the policy table publishes."""
    assert len(_CHALLENGE_MARKERS) == len(set(_CHALLENGE_MARKERS))
