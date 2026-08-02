"""
Tests for the Google broad-search discovery tier: domain typing and the
strict/priority gate. These run without a real key by patching the client and
the repo/settings lookups.
"""
import pytest

from app.scraping import source_discovery as sd


def test_classify_web_url_types_by_domain():
    brand_hosts = {"kenwoodpakistan.pk"}
    trusted_hosts = {"japanelectronics.pk", "surmawala.pk"}

    official = sd.classify_web_url(
        "https://kenwoodpakistan.pk/p/x", brand_hosts, trusted_hosts, "Kenwood")
    retailer = sd.classify_web_url(
        "https://surmawala.pk/products/x", brand_hosts, trusted_hosts, "Kenwood")
    random = sd.classify_web_url(
        "https://randomblog.com/review", brand_hosts, trusted_hosts, "Kenwood")

    assert official["source_type"] == "official"
    assert retailer["source_type"] == "trusted_secondary"
    assert random["source_type"] == "web"
    # Google results are product pages, used directly.
    assert all(s["is_direct"] == "true" for s in (official, retailer, random))


def test_brand_name_in_domain_is_treated_as_official():
    """A brand-owned host not yet in aliases is still recognised by its name."""
    typed = sd.classify_web_url("https://haier.com/pk/x", set(), set(), "Haier")
    assert typed["source_type"] == "official"


@pytest.fixture
def patched_repos(monkeypatch):
    async def fake_aliases(_brand):
        return ["kenwoodpakistan.pk"]

    async def fake_trusted():
        return [{"domain": "surmawala.pk"}]

    monkeypatch.setattr(sd.sources_repo, "get_brand_aliases", fake_aliases)
    monkeypatch.setattr(sd.sources_repo, "get_active_trusted_secondary_sources", fake_trusted)

    # `configured` is a read-only property; set the underlying key + cx so it
    # reports True, then force the search results.
    monkeypatch.setattr(sd.google_search_client, "api_key", "k", raising=False)
    monkeypatch.setattr(sd.google_search_client, "cx", "cx", raising=False)

    async def fake_search(_q):
        return [
            "https://kenwoodpakistan.pk/p/klu",   # official
            "https://surmawala.pk/products/klu",  # trusted
            "https://randomblog.com/klu-review",  # web
        ]

    monkeypatch.setattr(sd.google_search_client, "search", fake_search)
    # Bypass the persistent cache in tests.
    monkeypatch.setattr(sd, "_get_cached_google_urls", lambda q: _async_none())
    monkeypatch.setattr(sd, "_cache_google_urls", lambda q, u: _async_none())


async def _async_none():
    return None


def _set_mode(monkeypatch, mode):
    from app.db.repositories import settings as settings_module

    async def fake_get_setting(key):
        return mode if key == "source_mode" else None

    monkeypatch.setattr(settings_module.settings_repo, "get_setting", fake_get_setting)


@pytest.mark.asyncio
async def test_strict_mode_drops_web_sources(patched_repos, monkeypatch):
    _set_mode(monkeypatch, "strict")
    sources = await sd._tier_google_search("Kenwood", "KLU-12B03S")
    types = {s["source_type"] for s in sources}
    assert "web" not in types, "strict mode must never introduce an unvetted site"
    assert "official" in types and "trusted_secondary" in types


@pytest.mark.asyncio
async def test_priority_mode_keeps_web_sources(patched_repos, monkeypatch):
    _set_mode(monkeypatch, "priority")
    sources = await sd._tier_google_search("Kenwood", "KLU-12B03S")
    types = {s["source_type"] for s in sources}
    assert "web" in types, "priority mode keeps web as a fallback"


@pytest.mark.asyncio
async def test_tier_is_inactive_without_a_key(monkeypatch):
    monkeypatch.setattr(sd.google_search_client, "api_key", None, raising=False)
    monkeypatch.setattr(sd.google_search_client, "cx", None, raising=False)
    assert await sd._tier_google_search("Kenwood", "KLU-12B03S") == []
