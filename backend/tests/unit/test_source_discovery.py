"""
Tests for tiered source discovery.

Background: free search-engine scraping was measured and rejected (DuckDuckGo /
Startpage blocked, Mojeek CAPTCHA, Bing geo-locked and rate-limited after ~2
queries), so discovery runs on authoritative domains from the database instead.
The critical property under test is that a discovery FAILURE is never silently
turned into "this product has no facts".
"""
import pytest

from app.scraping import source_discovery
from app.scraping.source_discovery import (
    _normalise_domain,
    build_search_url_candidates,
    build_site_search_url,
    resolve_sources,
    search_result_mentions_product,
    template_of_url,
)


# --- Helpers ----------------------------------------------------------------

def test_normalise_domain_strips_scheme_and_www():
    assert _normalise_domain("https://www.Japanelectronics.PK/some/path") == "japanelectronics.pk"
    assert _normalise_domain("surmawala.pk") == "surmawala.pk"
    assert _normalise_domain("") == ""


def test_site_search_url_honours_an_explicit_template():
    url = build_site_search_url(
        "example.pk", "Kenwood", "KLU-12B03S",
        template="https://{domain}/?s={query}&post_type=product",
    )
    assert url == "https://example.pk/?s=Kenwood+KLU-12B03S&post_type=product"


def test_candidates_cover_wordpress_shopify_and_magento():
    """
    Must work on ANY storefront without being told the platform, so the
    candidate set spans the common ones rather than assuming one.
    """
    urls = build_search_url_candidates("example.pk", "Kenwood", "KLU-12B03S")
    joined = " ".join(urls)
    assert "/search?q=" in joined          # Shopify + many custom
    assert "post_type=product" in joined   # WooCommerce
    assert "/?s=" in joined                # WordPress generic
    assert "catalogsearch" in joined       # Magento
    assert len(urls) == len(set(urls)), "candidates must not repeat"


def test_known_working_template_is_tried_first():
    """A site already proven to work must cost one request, not five."""
    known = "https://{domain}/?s={query}&post_type=product"
    urls = build_search_url_candidates("example.pk", "Kenwood", "KLU-12B03S", known_template=known)
    assert urls[0] == "https://example.pk/?s=Kenwood+KLU-12B03S&post_type=product"
    assert len(urls) == len(set(urls)), "the promoted template must not also appear later"


def test_result_validation_detects_the_model_number():
    """
    This check is what removes the need for platform detection: the model number
    appearing IS the proof that the search worked.
    """
    assert search_result_mentions_product("... Kenwood KLU-12B03S 1 Ton AC ...", "KLU-12B03S")
    # Punctuation/spacing differences must still match.
    assert search_result_mentions_product("Kenwood KLU 12B03S inverter", "KLU-12B03S")
    assert search_result_mentions_product("klu12b03s", "KLU-12B03S")


def test_result_validation_rejects_a_no_results_page():
    """
    A page that loads but never names the product did NOT find it. Passing such
    a page to the Extractor would invite it to describe unrelated products.
    """
    assert not search_result_mentions_product(
        "Sorry, no products were found matching your search. Browse our categories.",
        "KLU-12B03S",
    )
    assert not search_result_mentions_product("", "KLU-12B03S")


def test_template_of_url_round_trips_for_caching():
    url = build_site_search_url("example.pk", "Kenwood", "KLU-12B03S",
                                template="https://{domain}/?s={query}")
    assert template_of_url("example.pk", url, "Kenwood", "KLU-12B03S") == "https://{domain}/?s={query}"


# --- Tier behaviour ---------------------------------------------------------

@pytest.mark.asyncio
async def test_falls_back_to_trusted_secondary_when_no_brand_domain(monkeypatch):
    """With brand_domain_aliases empty (its real state), tier 3 must still fire."""
    async def no_aliases(_brand):
        return []

    async def secondary():
        return [
            {"domain": "japanelectronics.pk", "label": "Japan Electronics"},
            {"domain": "surmawala.pk", "label": "Surmawala"},
        ]

    monkeypatch.setattr(source_discovery.sources_repo, "get_brand_aliases", no_aliases)
    monkeypatch.setattr(source_discovery.sources_repo, "get_active_trusted_secondary_sources", secondary)
    monkeypatch.setattr(source_discovery.firecrawl_client, "app", None)

    sources = await resolve_sources("Kenwood", "KLU-12B03S")
    # Several candidate URLs per domain, since the platform is unknown up front.
    assert {s["domain"] for s in sources} == {"japanelectronics.pk", "surmawala.pk"}
    assert all(s["source_type"] == "trusted_secondary" for s in sources)
    assert len(sources) == len({s["url"] for s in sources}), "no duplicate URLs"


@pytest.mark.asyncio
async def test_official_brand_domain_is_ordered_before_secondary(monkeypatch):
    async def aliases(_brand):
        return ["kenwood.com.pk"]

    async def secondary():
        return [{"domain": "japanelectronics.pk", "label": "Japan Electronics"}]

    monkeypatch.setattr(source_discovery.sources_repo, "get_brand_aliases", aliases)
    monkeypatch.setattr(source_discovery.sources_repo, "get_active_trusted_secondary_sources", secondary)
    monkeypatch.setattr(source_discovery.firecrawl_client, "app", None)

    sources = await resolve_sources("Kenwood", "KLU-12B03S")
    assert sources[0]["source_type"] == "official"
    assert "kenwood.com.pk" in sources[0]["url"]


@pytest.mark.asyncio
async def test_works_with_arbitrary_user_configured_domains(monkeypatch):
    """
    No retailer is special-cased. Whatever domains the user configures in
    Settings -> Trusted Secondary Sources are used; the seeded Japan
    Electronics/Surmawala rows are removable defaults, not requirements.
    """
    async def no_aliases(_brand):
        return []

    async def user_chosen():
        return [
            {"domain": "some-new-retailer.pk", "label": "New Retailer"},
            {"domain": "another-store.com", "label": "Another Store"},
        ]

    monkeypatch.setattr(source_discovery.sources_repo, "get_brand_aliases", no_aliases)
    monkeypatch.setattr(source_discovery.sources_repo, "get_active_trusted_secondary_sources", user_chosen)
    monkeypatch.setattr(source_discovery.firecrawl_client, "app", None)

    sources = await resolve_sources("Kenwood", "KLU-12B03S")
    assert {s["domain"] for s in sources} == {"some-new-retailer.pk", "another-store.com"}
    # Every candidate pattern is offered for each new domain, so a site on any
    # platform is discoverable without being told which platform it runs.
    assert all(
        any(p.format(domain=d, query="x").split("?")[0] in " ".join(
            s["url"] for s in sources if s["domain"] == d)
            for p in source_discovery.CANDIDATE_SEARCH_PATTERNS)
        for d in ("some-new-retailer.pk", "another-store.com")
    )


@pytest.mark.asyncio
async def test_removing_all_sources_escalates_rather_than_falling_back_to_defaults(monkeypatch):
    """
    If the user clears the source list, the system must escalate -- never
    quietly fall back to a built-in retailer they deliberately removed.
    """
    async def nothing(*_args):
        return []

    monkeypatch.setattr(source_discovery.sources_repo, "get_brand_aliases", nothing)
    monkeypatch.setattr(source_discovery.sources_repo, "get_active_trusted_secondary_sources", nothing)
    monkeypatch.setattr(source_discovery.firecrawl_client, "app", None)

    assert await resolve_sources("Kenwood", "KLU-12B03S") == []


@pytest.mark.asyncio
async def test_returns_empty_when_every_tier_is_empty(monkeypatch):
    """
    Empty means "no trustworthy source reached" and MUST escalate upstream --
    it must never be read as "this product legitimately has no facts".
    """
    async def nothing(*_args):
        return []

    monkeypatch.setattr(source_discovery.sources_repo, "get_brand_aliases", nothing)
    monkeypatch.setattr(source_discovery.sources_repo, "get_active_trusted_secondary_sources", nothing)
    monkeypatch.setattr(source_discovery.firecrawl_client, "app", None)

    assert await resolve_sources("Kenwood", "KLU-12B03S") == []


@pytest.mark.asyncio
async def test_one_failing_tier_does_not_abort_discovery(monkeypatch):
    """A DB hiccup in one tier must fall through, not lose the product."""
    async def boom(_brand):
        raise RuntimeError("transient DB error")

    async def secondary():
        return [{"domain": "surmawala.pk", "label": "Surmawala"}]

    monkeypatch.setattr(source_discovery.sources_repo, "get_brand_aliases", boom)
    monkeypatch.setattr(source_discovery.sources_repo, "get_active_trusted_secondary_sources", secondary)
    monkeypatch.setattr(source_discovery.firecrawl_client, "app", None)

    sources = await resolve_sources("Kenwood", "KLU-12B03S")
    assert sources, "the surviving tier must still produce sources"
    assert {s["domain"] for s in sources} == {"surmawala.pk"}


@pytest.mark.asyncio
async def test_duplicate_urls_are_collapsed(monkeypatch):
    async def aliases(_brand):
        return ["surmawala.pk"]  # same host as the secondary source below

    async def secondary():
        return [{"domain": "surmawala.pk", "label": "Surmawala"}]

    monkeypatch.setattr(source_discovery.sources_repo, "get_brand_aliases", aliases)
    monkeypatch.setattr(source_discovery.sources_repo, "get_active_trusted_secondary_sources", secondary)
    monkeypatch.setattr(source_discovery.firecrawl_client, "app", None)

    sources = await resolve_sources("Kenwood", "KLU-12B03S")
    urls = [s["url"] for s in sources]
    assert len(urls) == len(set(urls)), "the same URL must not be scraped twice"
    assert all(s["source_type"] == "official" for s in sources), "higher-trust tier must win"
