"""
Tests for the optional Google Programmable Search client.

The one behaviour that must never regress: with no key configured, or on any
failure, it returns [] so discovery falls through to the next tier instead of
crashing.
"""
import httpx
import pytest

from app.scraping import google_search_client as module
from app.scraping.google_search_client import GoogleSearchClient


def _client(monkeypatch, key, cx):
    monkeypatch.setattr(module.settings, "GOOGLE_SEARCH_API_KEY", key, raising=False)
    monkeypatch.setattr(module.settings, "GOOGLE_SEARCH_CX", cx, raising=False)
    return GoogleSearchClient()


@pytest.mark.asyncio
async def test_returns_empty_when_unconfigured(monkeypatch):
    """No key -> [] and, crucially, no HTTP call is attempted."""
    client = _client(monkeypatch, None, None)
    assert client.configured is False
    assert await client.search("Haier HRF-246 IPGA") == []


@pytest.mark.asyncio
async def test_returns_empty_when_only_one_of_key_or_cx_is_set(monkeypatch):
    assert _client(monkeypatch, "k", None).configured is False
    assert _client(monkeypatch, None, "cx").configured is False


@pytest.mark.asyncio
async def test_parses_result_links(monkeypatch):
    client = _client(monkeypatch, "k", "cx")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"items": [
            {"link": "https://japanelectronics.pk/products/haier-hrf-246-ipga"},
            {"link": "https://surmawala.pk/products/haier-hrf-246-ipga"},
            {"link": "https://japanelectronics.pk/products/haier-hrf-246-ipga"},  # dup
        ]})

    transport = httpx.MockTransport(handler)
    real_async_client = httpx.AsyncClient

    def patched(*args, **kwargs):
        kwargs["transport"] = transport
        return real_async_client(*args, **kwargs)

    monkeypatch.setattr(module.httpx, "AsyncClient", patched)

    urls = await client.search("Haier HRF-246 IPGA")
    assert urls == [
        "https://japanelectronics.pk/products/haier-hrf-246-ipga",
        "https://surmawala.pk/products/haier-hrf-246-ipga",
    ], "duplicates collapse, order preserved"


@pytest.mark.asyncio
async def test_quota_exceeded_returns_empty_not_error(monkeypatch):
    client = _client(monkeypatch, "k", "cx")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": {"message": "quota"}})

    transport = httpx.MockTransport(handler)
    real_async_client = httpx.AsyncClient
    monkeypatch.setattr(
        module.httpx, "AsyncClient",
        lambda *a, **k: real_async_client(*a, **{**k, "transport": transport}),
    )

    assert await client.search("anything") == []


@pytest.mark.asyncio
async def test_network_error_returns_empty(monkeypatch):
    client = _client(monkeypatch, "k", "cx")

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom")

    transport = httpx.MockTransport(handler)
    real_async_client = httpx.AsyncClient
    monkeypatch.setattr(
        module.httpx, "AsyncClient",
        lambda *a, **k: real_async_client(*a, **{**k, "transport": transport}),
    )

    assert await client.search("anything") == []


@pytest.mark.asyncio
async def test_missing_items_key_returns_empty(monkeypatch):
    """Google omits `items` entirely when there are zero results."""
    client = _client(monkeypatch, "k", "cx")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"searchInformation": {"totalResults": "0"}})

    transport = httpx.MockTransport(handler)
    real_async_client = httpx.AsyncClient
    monkeypatch.setattr(
        module.httpx, "AsyncClient",
        lambda *a, **k: real_async_client(*a, **{**k, "transport": transport}),
    )

    assert await client.search("nonexistent product") == []
