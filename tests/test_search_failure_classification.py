"""A missing dependency must not be reported as a provider outage.

## The measurement

On a machine with a SOCKS proxy configured but no `socksio` installed, every search fails:

    "Using SOCKS proxy, but the 'socksio' package is not installed.
     Make sure to install httpx using `pip install httpx[socks]`."

`_classify_exception` returned `PROVIDER` / `SEARCH_BACKEND_FAILED` - the same bucket as an
upstream outage. Three unrelated failures shared one label:

    missing socksio           -> provider
    ValueError("socksio ...") -> provider
    RuntimeError("other")     -> provider

The first names its own remedy. Telling a reader "backend failed" sends them to the network;
they should be told to install a package.

## The line these tests draw

`CONFIG` for an installation problem, `PROVIDER` for everything else - including a
server-side "not installed correctly", which is emphatically not something the caller can fix
locally. Phrase matching is blunt, so the boundary is pinned explicitly.
"""

from __future__ import annotations

import pytest

from webscout_mcp.search_provider import SearchFailureKind
from webscout_mcp.search_provider_adapter import SearchBackendAdapter


@pytest.fixture
def classify():
    adapter = SearchBackendAdapter.__new__(SearchBackendAdapter)
    return adapter._classify_exception


SOCKSIO_REAL = ImportError(
    "Using SOCKS proxy, but the 'socksio' package is not installed. "
    "Make sure to install httpx using `pip install httpx[socks]`."
)


def test_a_real_import_error_is_config(classify):
    _code, kind = classify(SOCKSIO_REAL)
    assert kind is SearchFailureKind.CONFIG


def test_a_wrapped_missing_dependency_is_config(classify):
    """The exception type is lost once wrapped; the text is what survives."""
    _code, kind = classify(ValueError("socksio not installed"))
    assert kind is SearchFailureKind.CONFIG


@pytest.mark.parametrize(
    "message",
    [
        "pip install httpx[socks]",
        "No module named 'socksio'",
        "missing dependency: socksio",
        "the required package is not installed",
    ],
)
def test_installation_phrases_are_config(classify, message):
    _code, kind = classify(RuntimeError(message))
    assert kind is SearchFailureKind.CONFIG, message


@pytest.mark.parametrize(
    "message",
    [
        "upstream service is not installed correctly",
        "connection refused",
        "something else broke",
        "unexpected token in response body",
    ],
)
def test_other_failures_stay_provider(classify, message):
    """The guard must not swallow genuine backend problems."""
    _code, kind = classify(RuntimeError(message))
    assert kind is SearchFailureKind.PROVIDER, message


def test_httpx_transport_classification_is_unchanged(classify):
    """The branches that already worked must keep working."""
    httpx = pytest.importorskip("httpx")
    _code, kind = classify(httpx.ConnectError("boom"))
    assert kind is SearchFailureKind.NETWORK
    _code, kind = classify(httpx.TimeoutException("slow"))
    assert kind is SearchFailureKind.TIMEOUT
