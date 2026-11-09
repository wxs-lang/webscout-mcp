"""Non-English challenge pages must be recognised, without false positives.

Found on 36kr: 58 characters of "火山引擎 正在进行安全检测... 为保障您的访问安全，系统正在
检测当前网络环境". None of the eight English/Cloudflare markers matched, so the page
was only escalated by luck - 25KB of script-heavy HTML tripped the low-density gate.
The same challenge on a small document would have been accepted as a genuine short
page and served to the caller.

Two things needed fixing and both are pinned here:

1. the marker set was English-only
2. the scan read only `html[:4096]`, but the marker sat at byte 25065 of 25258 -
   the head is boilerplate and inline CSS. The extracted body has it at position 0.
"""

from __future__ import annotations

import pytest

from webscout_mcp.fetch_escalation import (
    EscalationReason,
    _looks_like_challenge,
    should_escalate_to_browser,
)
from webscout_mcp.fetch_provider import FetchResponse
from webscout_mcp.recovery import RecoveryAction, RecoveryReason, classify_recovery


def _resp(content: str, raw_html: str = "", status: int = 200) -> FetchResponse:
    return FetchResponse(
        url="https://example.test/",
        final_url="https://example.test/",
        status_code=status,
        provider="http",
        content=content,
        content_type="text/html; charset=utf-8",
        extracted=bool(content),
        extraction_status="ok" if content else None,
        raw_html=raw_html,
    )


# --- The real page ----------------------------------------------------

CHALLENGE_BODY = (
    "火山引擎\n\n正在进行安全检测...\n\n为保障您的访问安全，系统正在检测当前网络环境，该过程通常需要几秒钟，请耐心等待"
)


def test_chinese_challenge_markers_are_recognised():
    assert _looks_like_challenge(f"<html><body>{CHALLENGE_BODY}</body></html>")


def test_challenge_marker_in_the_body_is_found_even_when_the_head_is_clean():
    """The 36kr shape: 25KB of boilerplate first, marker far past the 4KB window."""
    head = "<!DOCTYPE html><html><head>" + "<style>* { box-sizing: border-box }</style>" * 600 + "</head>"
    raw = head + f"<body>{CHALLENGE_BODY}</body></html>"
    assert len(raw) > 4096
    # The head-only scan genuinely misses it - that is why the body is also checked.
    assert _looks_like_challenge(raw[:4096]) is False
    assert _looks_like_challenge(CHALLENGE_BODY)


def test_real_challenge_page_escalates_as_challenge():
    d = should_escalate_to_browser(_resp(content=CHALLENGE_BODY, raw_html="<html><body>x</body></html>"))
    assert d.escalate is True
    assert d.reason_code is EscalationReason.CHALLENGE


def test_classification_reports_challenge_and_asks_for_a_browser():
    d = classify_recovery(_resp(content=CHALLENGE_BODY, raw_html="<html><body>x</body></html>"))
    assert d.reason is RecoveryReason.CHALLENGE
    assert d.action is RecoveryAction.BROWSER


# --- False positives must stay at zero --------------------------------


@pytest.mark.parametrize(
    ("label", "content"),
    [
        ("about", "关于我们 我们是一家专注于技术创新的公司，成立于 2010 年。联系我们：info@example.com"),
        ("login", "登录 请输入您的用户名和密码 忘记密码？"),
        ("product", "产品介绍 本产品支持多种部署方式，适用于各类企业场景，详情请咨询销售团队。"),
        ("english", "This domain is for use in documentation examples without needing permission."),
    ],
)
def test_legitimate_short_pages_are_not_flagged_as_challenges(label, content):
    """Broader phrases (请耐心等待, 验证码, 人机验证) were rejected for exactly this
    reason - they appear in ordinary copy and on real login flows."""
    d = should_escalate_to_browser(_resp(content=content, raw_html=f"<html><body>{content}</body></html>"))
    assert d.reason_code is not EscalationReason.CHALLENGE, f"{label} was misread as a challenge"


def test_marker_set_stays_narrow():
    """A guard on the guard: three Chinese markers, not a phrase dump."""
    from webscout_mcp.fetch_escalation import _CHALLENGE_MARKERS

    chinese = [m for m in _CHALLENGE_MARKERS if any("\u4e00" <= ch <= "\u9fff" for ch in m)]
    assert set(chinese) == {"安全检测", "检测当前网络环境", "火山引擎"}
