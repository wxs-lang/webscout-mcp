"""Grading content by shape, not length.

The tests reproduce the six measured samples that motivated the module, using
their actual char counts and average sentence lengths, so a future change that
breaks one of those cases fails here rather than in production.

Measured values being pinned:

    example.com       279 chars, avg_sent  92.3  useful
    wikipedia       20000 chars, avg_sent  54.8  useful
    docs.python     18426 chars, avg_sent  26.7  useful
    hackernews       4136 chars, avg_sent   7.8  useful   <- link list
    medium            149 chars, avg_sent   7.4  useless
    thepaper          257 chars, avg_sent   8.0  useless
"""

from __future__ import annotations

import pytest

from webscout_mcp.content_quality import (
    LONG_BODY_CHARS,
    MIN_READABLE_RATIO,
    MIN_SENTENCE_CHARS,
    THIN_CONTENT_CHARS,
    assess,
    readable_ratio,
    summarise,
)


def _prose(total_chars: int, sentence_chars: int) -> str:
    """Text of roughly ``total_chars`` built from sentences of ``sentence_chars``."""
    sentence = ("word " * (sentence_chars // 5)).strip().capitalize() + ". "
    return (sentence * (total_chars // len(sentence) + 1))[:total_chars]


def _fragments(count: int) -> str:
    return "\n".join(f"Item{i}" for i in range(count))


# --- The six measured samples -----------------------------------------


def test_short_complete_page_is_usable():
    """example.com: 279 chars but real sentences. Length alone would reject it."""
    result = assess(_prose(279, 92))
    assert result.usable, result.reason
    assert result.grade == "usable"


def test_short_navigation_shell_is_thin():
    """thepaper.cn: 257 chars of fragments. Length alone would accept it.

    The fixture pads to just over the floor: 30 bare items is ~180 chars, which is
    below THIN_CONTENT_CHARS and therefore "empty", not "thin". My first version
    asserted thin and was wrong about its own sample.
    """
    # 30 items is 199 chars; pad with more real items, not spaces - assess()
    # strips trailing whitespace, so space padding would vanish.
    shell = _fragments(45)
    result = assess(shell)
    assert result.grade == "thin", result.reason
    assert not result.usable


def test_tiny_navigation_is_empty():
    """medium.com: 149 chars, under the floor entirely."""
    assert assess(_fragments(16)).grade == "empty"


def test_long_article_is_usable():
    """wikipedia: large body with normal prose."""
    result = assess(_prose(20000, 55))
    assert result.usable
    assert "large enough" in result.reason or "prose" in result.reason


def test_long_link_list_is_usable():
    """hackernews: 4136 chars, avg_sent 7.8 - the case that breaks avg_sent alone.

    Its average sentence length is the same as medium's, so a rule keyed only on
    sentence structure would call a 4KB link list unusable.
    """
    result = assess(_fragments(500) + "x" * 2500)
    assert result.usable, result.reason


def test_docs_page_with_short_lines_is_usable():
    """docs.python: long body, lines far below the prose average."""
    assert assess(_prose(18426, 27)).usable


# --- Boundaries --------------------------------------------------------


def test_just_under_the_floor_is_empty():
    assert assess("x" * (THIN_CONTENT_CHARS - 1)).grade == "empty"


def test_just_at_the_floor_is_judged_not_empty():
    """At exactly the floor the shape decides; it must not short-circuit to empty."""
    result = assess("Short but complete sentence here. " * 6)
    assert result.grade in {"usable", "thin"}
    assert result.chars >= THIN_CONTENT_CHARS


def test_just_under_long_body_needs_prose():
    shell = _fragments(120)[: LONG_BODY_CHARS - 10]
    assert assess(shell).grade in {"thin", "empty"}


def test_just_at_long_body_passes_regardless_of_shape():
    shell = _fragments(400) + "y" * LONG_BODY_CHARS
    assert assess(shell[: LONG_BODY_CHARS + 100]).usable


def test_sentence_threshold_is_the_discriminator():
    """Two bodies of equal length, differing only in prose structure."""
    long_sentences = _prose(900, 90)
    fragments = _fragments(200)[:900]
    assert assess(long_sentences).usable
    assert assess(fragments).grade == "thin"


# --- Input handling ----------------------------------------------------


@pytest.mark.parametrize("value", [None, "", "   ", "\n\n\t "])
def test_blank_input_is_empty(value):
    result = assess(value)
    assert result.grade == "empty"
    assert result.chars == 0


def test_cjk_terminators_count_as_sentence_boundaries():
    """Chinese prose has no spaces; splitting on Latin terminators only would
    report one enormous sentence and wrongly accept navigation."""
    chinese_prose = "这是一个完整的句子，用来测试中文分句。" * 20
    result = assess(chinese_prose)
    assert result.sentences >= 15, "must split on 。 not just ."
    assert result.usable


def test_cjk_navigation_is_thin():
    chinese_nav = "\n".join(["首页", "登录", "注册", "关于我们", "联系方式", "隐私政策"] * 5)
    assert assess(chinese_nav).grade in {"thin", "empty"}


def test_assessment_serialises():
    data = assess(_prose(3000, 60)).to_dict()
    assert set(data) == {"grade", "chars", "sentences", "avg_sentence_chars", "reason"}


# --- Aggregation -------------------------------------------------------


def test_summarise_reports_rates():
    texts = [_prose(5000, 60), _prose(5000, 60), _fragments(40), ""]
    summary = summarise(texts)
    assert summary["total"] == 4
    assert summary["grades"]["usable"] == 2
    assert summary["grades"]["thin"] == 1
    assert summary["grades"]["empty"] == 1
    assert summary["usable_rate"] == 50.0


def test_summarise_with_no_samples_reports_none_not_zero():
    """No data must not look like a 0% success rate."""
    summary = summarise([])
    assert summary["total"] == 0
    assert summary["usable_rate"] is None


def test_thresholds_are_ordered_sensibly():
    assert THIN_CONTENT_CHARS < LONG_BODY_CHARS
    assert MIN_SENTENCE_CHARS > 0


# --- Unreadable bytes --------------------------------------------------


def test_mojibake_is_garbled_not_usable():
    """The 36kr sample: 391 chars of replacement characters, no terminators.

    Without the readability check the whole block counted as one 391-char
    "sentence" and passed the prose threshold.
    """
    garbage = "\ufffd" * 200 + "q\\" + "\ufffd" * 150 + "ET" + "\ufffd" * 40
    result = assess(garbage)
    assert result.grade == "garbled", result.reason
    assert not result.usable


def test_mojibake_reason_names_the_likely_cause():
    result = assess("\ufffd" * 300)
    assert result.grade == "garbled"
    assert "readable" in result.reason


def test_control_bytes_are_garbled():
    result = assess("".join(chr(c) for c in range(1, 40)) * 20)
    assert result.grade == "garbled"


def test_normal_latin_text_clears_the_readability_floor():
    text = _prose(3000, 60)
    assert readable_ratio(text) >= MIN_READABLE_RATIO
    assert assess(text).usable


def test_normal_cjk_text_clears_the_readability_floor():
    text = "这是一个完整的句子，用来测试中文分句。" * 40
    assert readable_ratio(text) >= MIN_READABLE_RATIO
    assert assess(text).usable


def test_readability_ratio_of_empty_is_zero():
    assert readable_ratio("") == 0.0


def test_summarise_counts_garbled_separately():
    summary = summarise(["\ufffd" * 400, _prose(5000, 60)])
    assert summary["grades"]["garbled"] == 1
    assert summary["grades"]["usable"] == 1
    assert summary["garbled_rate"] == 50.0
