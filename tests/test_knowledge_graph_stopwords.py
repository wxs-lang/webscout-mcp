"""Function words must not become entities.

## Measured on two real pages, before the fix

                       rust-book   python-docs
    entities                  50          50
    stopword entities         13 (26%)    8 (16%)
    relationships with a
      stopword in them        45 (100%)  39 (93%)
    heaviest relationship   the->in(524) the->in(694)

The highest-weighted relationship the tool produced was `the -> in`. Not a marginal weakness -
the top output was noise, and every consumer ranking by weight saw that first.

## Two causes, both measured

1. No stopword filtering: `The`, `This`, `If`, `In`, `But`, `It` were accepted by the
   capitalised-word pass and then linked to everything, because English prose is full of them.

2. A sentence-initial article glued onto the next word. For the sentence
   "The Rust programming language uses ownership." the old code produced three nodes:

       the_rust  'The Rust'  organization
       the       'The'       unknown
       rust      'Rust'      technology

   The same one-thing-three-nodes shape as the `python` / `tech_python` duplication this
   module already documents.

## What these tests pin

The boundary matters in both directions: dropping real names would be worse than keeping a
few function words. `Can`, `Will`, `May`, `Bill` are deliberately absent from the stopword set
because as capitalised tokens they are far more likely to be names.
"""

from __future__ import annotations

import pytest

from webscout_mcp.extras.knowledge_graph import KnowledgeGraphBuilder

BUILDER = KnowledgeGraphBuilder()


def _names(text: str) -> set[str]:
    return {e.name.lower() for e in BUILDER.extract_entities(text)}


@pytest.mark.parametrize(
    "word",
    ["The", "This", "That", "If", "In", "But", "It", "And", "For", "As", "When", "Which"],
)
def test_sentence_initial_function_words_are_not_entities(word):
    # The word appears at the start of a sentence, which is how it got capitalised.
    text = f"{word} ownership is a set of rules."
    assert word.lower() not in _names(text), f"{word!r} became an entity"


def test_a_leading_article_does_not_glue_onto_a_name():
    """`The Rust` must become `Rust`, not a third node next to `the` and `rust`."""
    names = _names("The Rust programming language uses ownership.")
    assert "the rust" not in names
    assert "the_rust" not in names
    assert "rust" in names, "the real name must survive"


def test_one_thing_yields_one_node():
    """Measured before the fix: three nodes for Rust in a single sentence."""
    entities = BUILDER.extract_entities("The Rust programming language uses ownership.")
    rust_like = [e for e in entities if "rust" in e.name.lower()]
    assert len(rust_like) == 1, [(e.id, e.name, e.type) for e in rust_like]


@pytest.mark.parametrize("name", ["Will", "Can", "May", "Bill", "Rose", "Mark"])
def test_ambiguous_capitalised_words_are_still_entities(name):
    """These are stopwords in NLP pipelines but names in prose - keep them."""
    text = f"We met {name} yesterday at the office."
    assert name.lower() in _names(text), f"{name!r} was dropped but can be a real name"


@pytest.mark.parametrize("name", ["Python", "Docker", "Kubernetes", "PostgreSQL"])
def test_technology_names_survive(name):
    text = f"{name} is widely used for this kind of work."
    assert name.lower() in _names(text)


def test_no_relationship_mentions_a_function_word():
    """The end-to-end assertion: composition, not just extraction."""
    text = (
        "The Rust programming language uses ownership. The compiler checks the rules in the "
        "code and the program will not compile if the rules are violated. It is strict."
    )
    graph = BUILDER.build(text)
    bad = [
        (r.source, r.target)
        for r in graph.relationships
        if r.source.lower() in {"the", "in", "if", "it", "and", "this", "that"}
        or r.target.lower() in {"the", "in", "if", "it", "and", "this", "that"}
    ]
    assert not bad, f"relationships touching a function word: {bad}"


def test_an_empty_or_function_word_only_text_yields_nothing():
    """No entities means no graph, rather than a graph of grammar."""
    assert BUILDER.extract_entities("The and but if in it.") == []
