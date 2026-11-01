"""Grade extracted content by shape, not just length.

## The problem with a character count

`observability` calls anything over 200 characters "usable". Measured on real
sites, that mislabels both directions:

    thepaper.cn  256 chars of navigation    -> called usable, is not
    medium.com   149 chars of navigation    -> correctly rejected, by luck
    example.com  279 chars, complete page   -> called usable, correctly

So the threshold is not wrong by a few units; it is measuring the wrong thing. A
short complete page and a long navigation shell differ in sentence structure, not
in volume.

## The rule

Separating them needs a layered test, because no single feature works. Measured:

    sample            chars   avg_sent   truth
    example.com         279       92.3   useful      short but real sentences
    wikipedia         20000       54.8   useful      long
    docs.python       18426       26.7   useful      long, short lines
    news.ycombinator   4136        7.8   useful      long, link list
    medium.com          149        7.4   useless     fragments
    thepaper.cn         256        7.9   useless     fragments

`avg_sent` alone would reject hackernews (7.8, same as medium). Length alone would
accept thepaper. Together they separate all six:

    unreadable bytes                      -> garbled
    < THIN_CONTENT_CHARS                  -> empty
    >= LONG_BODY_CHARS                    -> usable regardless of shape
    otherwise: avg_sent >= script floor   -> usable
               else                       -> thin

The sentence floor depends on script: CJK expresses the same content in fewer
characters, and an English-calibrated 30 rejected legitimate Chinese sentences
averaging 19.

## Scope

This grades content for measurement. It deliberately does not feed
`classify_recovery`: that path has its own tested thresholds, and changing recovery
behaviour is a separate decision with its own evidence burden.
"""

from __future__ import annotations

import re
import string
from dataclasses import dataclass

# Kept in step with observability.THIN_CONTENT_CHARS so the two cannot disagree
# about what counts as too small to judge.
THIN_CONTENT_CHARS = 200

# Above this, shape does not matter: a multi-kilobyte block of pure navigation is
# rare, and demanding sentence structure there caused false negatives on link lists
# (hackernews, 4136 chars, avg_sent 7.8).
LONG_BODY_CHARS = 2000

# Prose averages well above these per sentence; fragments and menu items do not.
# Two values because CJK packs more meaning per character.
MIN_SENTENCE_CHARS = 30.0
MIN_SENTENCE_CHARS_CJK = 12.0

# Share of characters a reader could actually read. Real Latin and CJK pages score
# above 0.95; a mojibake sample measured at runtime scored far below and was being
# graded usable because it had no sentence terminators to break it up.
MIN_READABLE_RATIO = 0.85

_SENTENCE_SPLIT = re.compile("[.!?\u3002\uff01\uff1f\n]+")

# Whitespace is legitimate but is not punctuation, so it is listed separately
# using code points rather than escape sequences.
_WHITESPACE = {chr(32), chr(9), chr(10), chr(13)}

# CJK punctuation that belongs in prose.
_CJK_PUNCT = set(
    "\u3001\u3002\uff0c\uff1b\uff1a\uff01\uff1f\uff08\uff09"
    "\u3010\u3011\u300a\u300b\u201c\u201d\u2018\u2019\u2014\u2026\u00b7\uffe5"
)

_READABLE = set(string.punctuation) | _WHITESPACE | _CJK_PUNCT


@dataclass(frozen=True)
class ContentAssessment:
    """Grade plus the measurements behind it."""

    grade: str  # "empty" | "thin" | "garbled" | "usable"
    chars: int
    sentences: int
    avg_sentence_chars: float
    reason: str

    @property
    def usable(self) -> bool:
        return self.grade == "usable"

    def to_dict(self) -> dict[str, object]:
        return {
            "grade": self.grade,
            "chars": self.chars,
            "sentences": self.sentences,
            "avg_sentence_chars": self.avg_sentence_chars,
            "reason": self.reason,
        }


def readable_ratio(text: str) -> float:
    """Fraction of characters that belong in readable prose.

    Deliberately permissive: letters, digits, whitespace and common punctuation in
    both Latin and CJK ranges pass. U+FFFD, control characters and other debris do
    not.
    """
    if not text:
        return 0.0
    good = sum(1 for ch in text if ch.isalnum() or ch in _READABLE)
    return good / len(text)


def _cjk_ratio(text: str) -> float:
    """Share of characters in the CJK ideograph block."""
    if not text:
        return 0.0
    cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    return cjk / len(text)


def sentence_threshold(text: str) -> float:
    """Minimum average sentence length for ``text``'s script mix.

    Pure Latin gets MIN_SENTENCE_CHARS, pure CJK gets MIN_SENTENCE_CHARS_CJK, and
    mixed text is interpolated so a bilingual page is not judged by the wrong
    yardstick.
    """
    ratio = _cjk_ratio(text)
    return round(MIN_SENTENCE_CHARS * (1 - ratio) + MIN_SENTENCE_CHARS_CJK * ratio, 1)


def _sentence_lengths(text: str) -> list[int]:
    parts = [segment.strip() for segment in _SENTENCE_SPLIT.split(text)]
    return [len(part) for part in parts if part]


def assess(text: str | None) -> ContentAssessment:
    """Grade ``text`` as empty, thin, garbled, or usable.

    Deterministic and network-free so it can be tested against the exact numbers
    that motivated it.
    """
    body = (text or "").strip()
    n = len(body)

    if n < THIN_CONTENT_CHARS:
        return ContentAssessment(
            grade="empty",
            chars=n,
            sentences=0,
            avg_sentence_chars=0.0,
            reason=f"only {n} chars, below the {THIN_CONTENT_CHARS}-char floor",
        )

    ratio = readable_ratio(body)
    if ratio < MIN_READABLE_RATIO:
        # Garbage that happens to be long is not content, and without this a block
        # with no sentence terminators counts as one enormous "sentence".
        return ContentAssessment(
            grade="garbled",
            chars=n,
            sentences=0,
            avg_sentence_chars=0.0,
            reason=(
                f"only {ratio * 100:.0f}% of {n} chars are readable "
                f"(floor {MIN_READABLE_RATIO * 100:.0f}%) - likely a decode or "
                f"compression fault upstream"
            ),
        )

    lengths = _sentence_lengths(body)
    avg = (sum(lengths) / len(lengths)) if lengths else 0.0

    if n >= LONG_BODY_CHARS:
        return ContentAssessment(
            grade="usable",
            chars=n,
            sentences=len(lengths),
            avg_sentence_chars=round(avg, 1),
            reason=f"{n} chars of body is large enough to read regardless of line shape",
        )

    threshold = sentence_threshold(body)
    if avg >= threshold:
        return ContentAssessment(
            grade="usable",
            chars=n,
            sentences=len(lengths),
            avg_sentence_chars=round(avg, 1),
            reason=(
                f"short body but sentences average {avg:.1f} chars of prose (floor {threshold} for this script mix)"
            ),
        )

    return ContentAssessment(
        grade="thin",
        chars=n,
        sentences=len(lengths),
        avg_sentence_chars=round(avg, 1),
        reason=(
            f"{n} chars in {len(lengths)} fragment(s), averaging {avg:.1f} chars "
            f"(floor {threshold} for this script mix) - too little prose to read, "
            f"likely navigation or chrome"
        ),
    )


def summarise(texts: list[str | None]) -> dict[str, object]:
    """Grade distribution over many samples, for SLO reporting."""
    grades = {"usable": 0, "thin": 0, "garbled": 0, "empty": 0}
    for text in texts:
        grades[assess(text).grade] += 1
    total = sum(grades.values())
    return {
        "total": total,
        "grades": grades,
        "usable_rate": round(grades["usable"] / total * 100, 1) if total else None,
        "thin_rate": round(grades["thin"] / total * 100, 1) if total else None,
        "garbled_rate": round(grades["garbled"] / total * 100, 1) if total else None,
        "empty_rate": round(grades["empty"] / total * 100, 1) if total else None,
    }
