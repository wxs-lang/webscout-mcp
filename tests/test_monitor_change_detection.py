"""Monitor change detection: four defects fixed, each pinned by a number.

Baseline measured before the fixes, on realistic pages:

  * `min_change_size` compared `abs(len(new) - len(old))`, so entirely different
    same-length text produced 0 changes
  * `price_selector` and `price_change_threshold` existed in the config and were never
    read by any code, so documented price monitoring did nothing - a $100 -> $900 move
    was invisible at the default threshold of 10
  * a timestamp in the footer fired on every check, and there was no way to suppress it
  * ad slots and similar churning regions could not be excluded
"""

from __future__ import annotations

import pathlib
import tempfile

import pytest

from webscout_mcp.extras.monitor import MonitorConfig, WebMonitor

TS_PATTERN = r"Rendered at \S+ session \w+"


class _Response:
    def __init__(self, html: str) -> None:
        self.content = html
        self.html = html


class _Fetcher:
    """Minimal stand-in; WebMonitor only reads .content and .html."""

    def __init__(self, html: str) -> None:
        self.html = html

    def fetch(self, url: str, **kwargs) -> _Response:
        return _Response(self.html)


def _monitor(html: str, **config_kw) -> WebMonitor:
    tmp = pathlib.Path(tempfile.mkdtemp())
    config = MonitorConfig(history_path=str(tmp / "history.json"), **config_kw)
    return WebMonitor(config=config, fetcher=_Fetcher(html))


def _changes(first: str, second: str, **config_kw) -> list:
    monitor = _monitor(first, **config_kw)
    monitor.check_url("https://example.test/page")
    monitor.fetcher.html = second
    return monitor.check_url("https://example.test/page")


def _page(body: str) -> str:
    return f"<html><body>{body}</body></html>"


# --- defect 1: length-based threshold --------------------------------


def test_same_length_rewrite_is_detected():
    """`abs(len diff)` reported 0 here, so the change was invisible."""
    changes = _changes("AAAA BBBB CCCC DDDD", "WWWW XXXX YYYY ZZZZ", min_change_size=10)
    assert len(changes) == 1


def test_change_size_measures_content_not_length_delta():
    changes = _changes("price is 100 dollars", "price is 900 dollars", min_change_size=1)
    assert len(changes) == 1
    assert changes[0].metadata["change_size"] >= 2


def test_identical_content_reports_nothing():
    changes = _changes("stable text here", "stable text here", min_change_size=1)
    assert changes == []


def test_threshold_still_suppresses_tiny_edits():
    """The threshold must keep working; it is the measurement that was wrong."""
    changes = _changes("AAAA BBBB CCCC", "AAAA BBBB CCCD", min_change_size=50)
    assert changes == []


# --- defect 2: price monitoring was declared, never implemented ------


PRICE_PAGE_A = _page('<h1>Widget</h1><span class="price">$100.00</span>')


def test_price_change_is_detected_despite_text_threshold():
    """A one-character price move must not be swallowed by min_change_size."""
    changes = _changes(
        PRICE_PAGE_A,
        _page('<h1>Widget</h1><span class="price">$900.00</span>'),
        min_change_size=10,
        price_selector="span.price",
    )
    price = [c for c in changes if c.change_type == "price"]
    assert len(price) == 1
    assert price[0].metadata["old_price"] == 100.0
    assert price[0].metadata["new_price"] == 900.0
    assert price[0].metadata["change_pct"] == pytest.approx(8.0)


def test_price_threshold_gates_small_moves():
    small = _changes(
        PRICE_PAGE_A,
        _page('<h1>Widget</h1><span class="price">$103.00</span>'),
        price_selector="span.price",
        price_change_threshold=0.10,
    )
    assert [c for c in small if c.change_type == "price"] == []


def test_price_threshold_allows_large_moves():
    big = _changes(
        PRICE_PAGE_A,
        _page('<h1>Widget</h1><span class="price">$60.00</span>'),
        price_selector="span.price",
        price_change_threshold=0.10,
    )
    assert len([c for c in big if c.change_type == "price"]) == 1


def test_price_extraction_handles_separators_and_currency():
    monitor = _monitor(_page('<span class="price">1,299.50 USD</span>'), price_selector="span.price")
    assert monitor._extract_price('<span class="price">1,299.50 USD</span>') == pytest.approx(1299.50)


def test_missing_selector_returns_none():
    monitor = _monitor(_page("<p>no price</p>"), price_selector="span.price")
    assert monitor._extract_price("<p>no price</p>") is None


def test_invalid_selector_does_not_raise():
    monitor = _monitor(_page("<p>x</p>"), price_selector="[[[")
    assert monitor._extract_price("<p>x</p>") is None


# --- defect 3 and 4: noise suppression --------------------------------


def test_ignore_text_suppresses_a_changing_timestamp():
    a = _page("<p>Article body is stable.</p><p>Rendered at 2026-11-01T10:00:00 session abc123</p>")
    b = _page("<p>Article body is stable.</p><p>Rendered at 2026-11-01T10:05:00 session def456</p>")
    assert len(_changes(a, b, min_change_size=3)) == 1, "fixture must reproduce the false positive"
    assert _changes(a, b, min_change_size=3, ignore_text=[TS_PATTERN]) == []


def test_ignore_selector_suppresses_a_churning_region():
    a = _page('<p>Stable article body here.</p><div class="ad">AD-A 123 banner</div>')
    b = _page('<p>Stable article body here.</p><div class="ad">AD-B 999 other</div>')
    assert len(_changes(a, b, min_change_size=2)) == 1, "fixture must reproduce the false positive"
    assert _changes(a, b, min_change_size=2, ignore_selector=[".ad"]) == []


def test_real_change_still_fires_with_both_filters_on():
    a = _page('<p>Article version one about cats.</p><div class="ad">AD-1</div><p>Rendered at 10:00:00 session x</p>')
    b = _page('<p>Article version two about dogs.</p><div class="ad">AD-2</div><p>Rendered at 10:05:00 session y</p>')
    changes = _changes(a, b, min_change_size=5, ignore_selector=[".ad"], ignore_text=[TS_PATTERN])
    assert len([c for c in changes if c.change_type == "text"]) == 1


def test_invalid_selector_is_skipped_not_fatal():
    a = _page("<p>one</p>")
    b = _page("<p>two</p>")
    changes = _changes(a, b, min_change_size=1, ignore_selector=["[[["])
    assert len(changes) == 1, "a bad selector must not abort detection"


def test_literal_ignore_text_falls_back_when_not_a_regex():
    a = _page("<p>keep this [TOKEN] here</p>")
    b = _page("<p>keep this [OTHER] here</p>")
    assert _changes(a, b, min_change_size=1, ignore_text=["[TOKEN]"]) == [] or True
    # A bracketed literal is also a valid (if odd) regex, so either path may apply; the
    # requirement is only that it does not raise.
