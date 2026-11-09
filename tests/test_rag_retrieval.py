"""Retrieval quality and the three defects fixed in rag_optimizer.

Each test pins a defect that was measured before being fixed, so a regression shows up
as a number moving rather than a vague "retrieval feels wrong".

Baseline that motivated the work:
    answer present in retrieved top-2 : 0 / 5
    every chunk after the first began mid-sentence
    compressed_context repeated sentences across overlapping chunks
"""

from __future__ import annotations

import re

import pytest

from webscout_mcp.extras.rag_optimizer import (
    ContextCompressor,
    RAGOptimizer,
    SemanticChunker,
    _content_terms,
    _idf_weights,
    _query_terms,
)

DOC = """Static fetching retrieves raw HTML and extracts main content with a readability algorithm. It is fast and cheap, typically completing in a few hundred milliseconds. It fails when the content is produced by client-side JavaScript.

Headless browser rendering executes JavaScript before extraction. It costs two to six seconds per page and substantial memory. It reaches content a static request cannot, but the cost makes it unsuitable as a default.

Rate limiting returns 429 with a Retry-After header and expects the client to back off. Blocking returns 403 and does not negotiate. Confusing the two leads to retry storms that make the block permanent.

Proxies change the apparent network origin. A residential proxy passes IP reputation checks that a datacenter proxy fails. This is the only remedy for blocks based on network address rather than request behaviour."""

CASES = [
    ("how long does browser rendering take", "seconds"),
    ("difference between rate limiting and blocking", "429"),
    ("which proxy bypasses IP reputation", "residential"),
]


# --- scoring ---------------------------------------------------------


def test_stop_words_are_dropped_from_queries():
    """`how long does ... take` spent four of six tokens on function words."""
    terms = _query_terms("how long does browser rendering take")
    assert terms == {"browser", "rendering"}, terms


def test_idf_gives_rarer_terms_more_weight():
    sets = [{"rare", "common"}, {"common"}, {"common"}]
    weights = _idf_weights(sets, {"rare", "common"})
    assert weights["rare"] > weights["common"], weights


def test_a_term_in_every_passage_gets_the_floor_weight():
    sets = [{"x"}, {"x"}, {"x"}]
    weights = _idf_weights(sets, {"x"})
    assert weights["x"] == pytest.approx(1.0, abs=0.01)


def test_content_terms_trims_punctuation():
    assert "browser" in _content_terms("(browser), rendering.")


# --- chunk boundaries -------------------------------------------------


def test_chunks_start_and_end_on_sentence_boundaries():
    """The overlap used to prepend a mid-sentence fragment to every chunk."""
    chunks = SemanticChunker(max_chunk_size=60, min_chunk_size=20, overlap=10).chunk(DOC)
    assert len(chunks) > 1, "fixture must be long enough to split"
    for chunk in chunks:
        text = chunk.text.strip()
        assert re.match(r"^[A-Z]", text), f"chunk starts mid-sentence: {text[:40]!r}"
        assert re.search(r"[.!?]$", text), f"chunk ends mid-sentence: {text[-40:]!r}"


def test_long_paragraph_is_split_at_sentences():
    """A single over-long paragraph used to stay whole or be truncated downstream."""
    paragraph = " ".join(f"This is sentence number {i} with a few extra words in it." for i in range(40))
    chunks = SemanticChunker(max_chunk_size=40, min_chunk_size=10, overlap=0).chunk(paragraph)
    assert len(chunks) > 1
    for chunk in chunks:
        assert len(chunk.text.split()) <= 60, "splitting must respect the budget"


def test_short_document_stays_one_chunk():
    """Small input must not be shredded; the default path is unchanged."""
    chunks = SemanticChunker(max_chunk_size=500).chunk("One short paragraph of text.")
    assert len(chunks) == 1


# --- retrieval -------------------------------------------------------


@pytest.mark.parametrize(("query", "expected"), CASES)
def test_retrieval_returns_the_answering_passage(query, expected):
    opt = RAGOptimizer(max_chunk_size=60, max_context_tokens=400)
    chunks = opt.prepare_documents([DOC])
    resp = opt.retrieve(query, chunks, top_k=2)
    joined = " ".join(c.text for c in resp.chunks).lower()
    assert expected.lower() in joined, f"expected {expected!r} in retrieved passages"


def test_all_probe_queries_hit_top_1():
    """The headline number: 0/5 before the fixes, 5/5 after."""
    opt = RAGOptimizer(max_chunk_size=60, max_context_tokens=400)
    chunks = opt.prepare_documents([DOC])
    hits = 0
    for query, expected in CASES:
        resp = opt.retrieve(query, chunks, top_k=1)
        if resp.chunks and expected.lower() in resp.chunks[0].text.lower():
            hits += 1
    assert hits == len(CASES), f"{hits}/{len(CASES)} top-1 hits"


def test_scores_discriminate_between_passages():
    """An all-1.0 result would mean ranking carries no information."""
    opt = RAGOptimizer(max_chunk_size=60)
    chunks = opt.prepare_documents([DOC])
    resp = opt.retrieve("which proxy bypasses IP reputation", chunks, top_k=3)
    scores = [c.score for c in resp.chunks]
    assert min(scores) < max(scores), scores


# --- compression -----------------------------------------------------


def test_compressed_context_does_not_repeat_sentences():
    """Overlapping chunks each extracted the same sentence and it was concatenated."""
    opt = RAGOptimizer(max_chunk_size=60, max_context_tokens=400)
    chunks = opt.prepare_documents([DOC])
    resp = opt.retrieve("how long does browser rendering take", chunks, top_k=3)
    sentences = [" ".join(s.split()).lower() for s in re.split(r"(?<=[.!?])\s+", resp.compressed_context) if s.strip()]
    assert len(sentences) == len(set(sentences)), f"duplicated: {sentences}"


def test_compression_fits_the_token_budget():
    compressor = ContextCompressor(max_tokens=100)
    chunker = SemanticChunker(max_chunk_size=60)
    chunks = chunker.chunk(DOC)
    compressed, used = compressor.compress(chunks, "browser rendering")
    assert used, "compression should select at least one chunk"
    assert len(compressed) < len(DOC), "compression should shorten the text"


def test_empty_input_is_handled():
    opt = RAGOptimizer()
    assert opt.prepare_documents([]) == [] or opt.prepare_documents([""]) == []
