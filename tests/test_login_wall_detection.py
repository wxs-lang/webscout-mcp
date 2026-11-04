"""A login wall behind a 200, and the scan window that hid it.

## Three defects, and only the combination moved the behaviour

1. `_looks_like_login_wall` scanned only the first 8 KB. Measured on zhihu.com, whose 45 KB
   document places every login marker at offset 12.5-18.5 KB.
2. The marker list knew only login *demands* ("please log in", "需要登录"). zhihu serves a
   login *form* - "验证码登录", "忘记密码", "登录/注册" - which matched nothing.
3. The check ran only inside the 403 branch, so a 200 carrying a wall was never examined.

Fixing any one alone changed nothing observable, which is what made an intermediate
verification misleading: markers were added and the 200 path was added, but the window was
still 8 KB, so the page still passed. These tests pin each of the three separately.

Measured before: `outcome=browser_success`, grade `usable`, a browser launch spent on a page
no browser can get past. After: `AUTH_REQUIRED` / `REQUIRE_AUTH` / `user_action_required`.
"""

from __future__ import annotations

import pytest

from webscout_mcp.fetch_provider import FetchResponse
from webscout_mcp.recovery import (
    LOGIN_WALL_SCAN_CHARS,
    RecoveryAction,
    RecoveryReason,
    _looks_like_login_wall,
    classify_recovery,
)

ZHIHU_LOGIN = (
    "打开知乎App 其他扫码方式：微信 下载知乎App 无障碍模式 验证码登录密码登录 "
    "开通机构号 获取短信验证码 忘记密码 登录/注册 其他方式登录 "
    "未注册手机验证后自动登录，注册即代表同意《知乎协议》《隐私保护指引》"
)


def test_the_scan_window_reaches_past_8kb():
    """The marker at offset 18 KB must be seen, or nothing else matters."""
    assert LOGIN_WALL_SCAN_CHARS >= 20_000
    padded = ("x" * 18_000) + "自动登录"
    assert _looks_like_login_wall(padded), "a login marker at 18 KB must be found; zhihu's sit at 12.5-18.5 KB"


def test_the_window_is_still_bounded():
    """It runs on every response, so it must not scan whole documents without limit."""
    assert LOGIN_WALL_SCAN_CHARS <= 200_000


@pytest.mark.parametrize(
    "marker",
    ["验证码登录", "登录/注册", "忘记密码", "获取短信验证码", "自动登录"],
)
def test_login_form_vocabulary_is_recognised(marker):
    """Control names, not sentences - article prose has no reason to contain them."""
    assert _looks_like_login_wall(f"<html><body>{marker}</body></html>")


def test_a_200_with_a_login_wall_requires_auth():
    response = FetchResponse(
        url="https://www.zhihu.com/",
        final_url="https://www.zhihu.com/",
        status_code=200,
        provider="http",
        content=ZHIHU_LOGIN,
        content_type="text/html; charset=utf-8",
        raw_html=ZHIHU_LOGIN,
    )
    decision = classify_recovery(response)
    assert decision.reason is RecoveryReason.AUTH_REQUIRED
    assert decision.action is RecoveryAction.REQUIRE_AUTH
    assert decision.details.get("escalation") == "LOGIN_WALL"


def test_a_200_with_a_wall_does_not_escalate():
    """A browser cannot supply credentials, so escalating is wasted work."""
    response = FetchResponse(
        url="https://www.zhihu.com/",
        final_url="https://www.zhihu.com/",
        status_code=200,
        provider="http",
        content=ZHIHU_LOGIN,
        content_type="text/html; charset=utf-8",
        raw_html=ZHIHU_LOGIN,
    )
    assert classify_recovery(response).action is not RecoveryAction.BROWSER


def test_ordinary_content_is_not_mistaken_for_a_wall():
    """The window is 6x wider now, so the false-positive surface matters more, not less."""
    article = (
        "Static fetching retrieves raw HTML and extracts the main content. "
        "A headless browser executes JavaScript when a page requires it. " * 200
    )
    assert not _looks_like_login_wall(article)


def test_a_page_linking_to_login_in_its_nav_is_not_a_wall():
    """A navigation link is not a demand; the markers are deliberately specific."""
    nav = "<nav><a href='/login'>Login</a> | <a href='/about'>About</a></nav>" + ("content " * 500)
    assert not _looks_like_login_wall(nav)
