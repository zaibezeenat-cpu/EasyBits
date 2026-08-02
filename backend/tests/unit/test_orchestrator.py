"""
Tests for scrape orchestration.

The central rule under test: a SEARCH-RESULTS page is never accepted as a
source. Storefronts echo the query back and return fuzzy matches, so a listing
can name the model while every product on it is something else -- observed live,
where a search for KLU-12B03S returned a page whose top hit was KGP-18C01S.
Only a product DETAIL page that names the model is evidence.
"""
import pytest

from app.scraping import orchestrator
from app.scraping.models import ScrapeResult


def _result(url: str, content: str, links=None) -> ScrapeResult:
    return ScrapeResult(
        url=url, content=content, engine_used="playwright",
        success=True, product_links=links or [],
    )


@pytest.fixture
def one_source(monkeypatch):
    async def sources(_brand, _model, **_kw):
        return [{"url": "https://shop.pk/search?q=x", "source_type": "trusted_secondary",
                 "domain": "shop.pk"}]

    async def noop(*_a, **_k):
        return None

    monkeypatch.setattr(orchestrator, "resolve_sources", sources)
    monkeypatch.setattr(orchestrator, "remember_working_template", noop)


@pytest.mark.asyncio
async def test_search_listing_without_a_product_page_is_discarded(one_source, monkeypatch):
    """
    The live failure this guards: the listing echoes "53 results for KLU-12B03S"
    but stocks a different model. It must NOT become a source.
    """
    async def fake_scrape(url, model_number=""):
        # Search page mentions the model only because the query is echoed back;
        # it offers no product link that matches.
        return _result(url, "53 results found for KLU-12B03S. Showing KGP-18C01S.", links=[])

    monkeypatch.setattr(orchestrator, "smart_fetch", fake_scrape)

    result = await orchestrator.scrape_product("Kenwood", "KLU-12B03S")
    assert "failure" in result
    assert result["failure"].category == "source_unreachable"


@pytest.mark.asyncio
async def test_blocked_source_reports_source_blocked_with_actionable_detail(one_source, monkeypatch):
    """
    A Cloudflare/anti-bot page loads but is not the product. It must escalate as
    `source_blocked` (telling the operator to paste Details), NOT the misleading
    `source_unreachable` ("product not listed").
    """
    async def fake_scrape(url, model_number=""):
        return _result(url, "Just a moment...\nEnable JavaScript and cookies to continue")

    monkeypatch.setattr(orchestrator, "smart_fetch", fake_scrape)

    result = await orchestrator.scrape_product("Kenwood", "KLU-12B03S")
    assert "failure" in result
    assert result["failure"].category == "source_blocked"
    assert "Details" in result["failure"].detail  # actionable guidance


@pytest.mark.asyncio
async def test_detail_page_naming_the_model_is_accepted(one_source, monkeypatch):
    async def fake_scrape(url, model_number=""):
        if "/products/" in url:
            return _result(url, "Kenwood KLU-12B03S 1.0 Ton Inverter AC. Capacity 1 Ton.")
        return _result(url, "53 results found for KLU-12B03S",
                       links=["https://shop.pk/products/kenwood-klu-12b03s"])

    monkeypatch.setattr(orchestrator, "smart_fetch", fake_scrape)

    result = await orchestrator.scrape_product("Kenwood", "KLU-12B03S")
    assert "failure" not in result
    data = result["scraped_data"]
    assert len(data) == 1
    # The DETAIL page is recorded as the source, not the search page.
    assert data[0]["url"] == "https://shop.pk/products/kenwood-klu-12b03s"
    assert "Capacity 1 Ton" in data[0]["content"]


@pytest.mark.asyncio
async def test_detail_page_for_the_wrong_product_is_rejected(one_source, monkeypatch):
    """Following a link that turns out to be a different model must not count."""
    async def fake_scrape(url, model_number=""):
        if "/products/" in url:
            return _result(url, "Kenwood KGP-18C01S 1.5 Ton Glory Pro AC")  # wrong model
        return _result(url, "53 results found for KLU-12B03S",
                       links=["https://shop.pk/products/kenwood-kgp-18c01s"])

    monkeypatch.setattr(orchestrator, "smart_fetch", fake_scrape)

    result = await orchestrator.scrape_product("Kenwood", "KLU-12B03S")
    assert "failure" in result


@pytest.mark.asyncio
async def test_no_configured_sources_escalates_clearly(monkeypatch):
    async def no_sources(_brand, _model, **_kw):
        return []

    monkeypatch.setattr(orchestrator, "resolve_sources", no_sources)

    result = await orchestrator.scrape_product("Kenwood", "KLU-12B03S")
    assert result["failure"].category == "no_reliable_source_found"


@pytest.mark.asyncio
async def test_a_scrape_exception_does_not_abort_the_product(one_source, monkeypatch):
    async def boom(url, model_number=""):
        raise RuntimeError("network died")

    monkeypatch.setattr(orchestrator, "smart_fetch", boom)

    result = await orchestrator.scrape_product("Kenwood", "KLU-12B03S")
    # Escalates cleanly rather than raising out of the pipeline.
    assert "failure" in result
