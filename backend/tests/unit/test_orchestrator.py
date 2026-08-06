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
    async def fake_scrape(url, model_number="", allow_tier2=True):
        return _result(url, "Just a moment...\nEnable JavaScript and cookies to continue")

    monkeypatch.setattr(orchestrator, "smart_fetch", fake_scrape)

    result = await orchestrator.scrape_product("Kenwood", "KLU-12B03S")
    assert "failure" in result
    assert result["failure"].category == "source_blocked"
    assert "Details" in result["failure"].detail  # actionable guidance


@pytest.mark.asyncio
async def test_detail_page_naming_the_model_is_accepted(one_source, monkeypatch):
    async def fake_scrape(url, model_number="", allow_tier2=True):
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
    async def fake_scrape(url, model_number="", allow_tier2=True):
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


# ---------------------------------------------------------------------------
# WHEN TO STOP SCRAPING.
#
# Measured on a real 2-product run (2026-08-03): 13 domains were tried; 2 gave a
# source in the first 9 seconds and 11 gave nothing over the next 128 seconds --
# 93% of scrape time spent confirming absences that changed no output. These pin
# the stop rules that end that, and equally pin that they do NOT fire early when
# stopping would actually cost information.
# ---------------------------------------------------------------------------


def _domains(*specs):
    """Build a resolve_sources stand-in: one search URL per (domain, source_type)."""
    async def sources(_brand, _model, **_kw):
        return [
            {"url": f"https://{d}/search?q=x", "source_type": st, "domain": d}
            for d, st in specs
        ]
    return sources


def _stocked(url: str, model: str = "WF-6807"):
    """
    A domain that genuinely carries the product: its search page names the model
    AND links to a detail page whose slug identifies it, which is what the
    orchestrator requires before accepting anything as a source.
    """
    from urllib.parse import urlparse
    if "/products/" in url:
        return _result(url, f"{model} full specifications")
    host = urlparse(url).netloc
    return _result(url, f"Search results for {model}",
                   links=[f"https://{host}/products/{model.lower()}"])


def _not_stocked(url: str):
    return _result(url, "No products found matching your search.")


@pytest.fixture
def _noop_template(monkeypatch):
    async def noop(*_a, **_k):
        return None
    monkeypatch.setattr(orchestrator, "remember_working_template", noop)


@pytest.mark.asyncio
async def test_stops_once_official_plus_one_is_collected(monkeypatch, _noop_template):
    """
    THE MAIN WIN. fact_corroboration treats an official source as authoritative
    on its own, so official + 1 cross-check already decides every field. The 11
    domains after that cost 128s and changed nothing.
    """
    visited: list[str] = []

    monkeypatch.setattr(orchestrator, "resolve_sources", _domains(
        ("brand.pk", "official"),
        ("shopA.pk", "trusted_secondary"),
        ("shopB.pk", "trusted_secondary"),   # must never be reached
        ("shopC.pk", "trusted_secondary"),
        ("shopD.pk", "trusted_secondary"),
    ))

    async def fake_scrape(url, model_number="", allow_tier2=True):
        visited.append(url)
        return _stocked(url)

    monkeypatch.setattr(orchestrator, "smart_fetch", fake_scrape)

    result = await orchestrator.scrape_product("WestPoint", "WF-6807")

    assert len(result["scraped_data"]) == 2
    assert not any("shopB" in u or "shopC" in u or "shopD" in u for u in visited), \
        f"kept scraping after corroboration was satisfied: {visited}"


@pytest.mark.asyncio
async def test_does_not_stop_early_without_an_official_source(monkeypatch, _noop_template):
    """
    Two RETAILERS are not the same as official + 1. Without an authoritative
    source the extra opinions are exactly what corroboration needs, so the early
    stop must stay shut -- speed must never be bought with accuracy here.
    """
    monkeypatch.setattr(orchestrator, "resolve_sources", _domains(
        ("shopA.pk", "trusted_secondary"),
        ("shopB.pk", "trusted_secondary"),
        ("shopC.pk", "trusted_secondary"),
    ))

    async def fake_scrape(url, model_number="", allow_tier2=True):
        return _stocked(url)

    monkeypatch.setattr(orchestrator, "smart_fetch", fake_scrape)

    result = await orchestrator.scrape_product("WestPoint", "WF-6807")

    # All three collected: none of them is authoritative, so none is redundant.
    assert len(result["scraped_data"]) == 3


@pytest.mark.asyncio
async def test_gives_up_after_consecutive_empty_domains(monkeypatch, _noop_template):
    """
    The no-official-source case the rule above deliberately does not cover. The
    configured list is ordered by trust, so once several consecutive domains have
    nothing, the tail does not either -- walking all 105 proves nothing slowly.
    """
    visited: list[str] = []
    monkeypatch.setattr(orchestrator, "resolve_sources", _domains(
        *[(f"dead{i}.pk", "trusted_secondary") for i in range(20)]
    ))

    async def fake_scrape(url, model_number="", allow_tier2=True):
        visited.append(url)
        return _not_stocked(url)

    monkeypatch.setattr(orchestrator, "smart_fetch", fake_scrape)

    result = await orchestrator.scrape_product("WestPoint", "WF-6807")

    assert "failure" in result
    assert len(visited) <= (orchestrator.MAX_CONSECUTIVE_EMPTY_DOMAINS + 1) * 2, (
        f"walked {len(visited)} dead domains; the diminishing-returns stop did not fire"
    )


@pytest.mark.asyncio
async def test_empty_domain_streak_resets_on_a_hit(monkeypatch, _noop_template):
    """
    The streak counts CONSECUTIVE misses. A domain that delivers must reset it,
    or a list with useful sources spread through it would be abandoned midway.
    """
    monkeypatch.setattr(orchestrator, "resolve_sources", _domains(
        ("dead1.pk", "trusted_secondary"),
        ("dead2.pk", "trusted_secondary"),
        ("dead3.pk", "trusted_secondary"),
        ("good.pk", "trusted_secondary"),     # resets the streak
        ("dead4.pk", "trusted_secondary"),
        ("dead5.pk", "trusted_secondary"),
        ("good2.pk", "trusted_secondary"),    # must still be reached
    ))

    async def fake_scrape(url, model_number="", allow_tier2=True):
        return _stocked(url) if "good" in url else _not_stocked(url)

    monkeypatch.setattr(orchestrator, "smart_fetch", fake_scrape)

    result = await orchestrator.scrape_product("WestPoint", "WF-6807")

    assert len(result["scraped_data"]) == 2, "the reset did not happen; good2.pk was never reached"
