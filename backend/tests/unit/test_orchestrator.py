"""
Tests for scrape orchestration.

The central rule under test: a SEARCH-RESULTS page is never accepted as a
source. Storefronts echo the query back and return fuzzy matches, so a listing
can name the model while every product on it is something else -- observed live,
where a search for KLU-12B03S returned a page whose top hit was KGP-18C01S.
Only a product DETAIL page that names the model is evidence.
"""
import httpx
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
    async def fake_scrape(url, model_number="", allow_tier2=True):
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
    async def boom(url, model_number="", allow_tier2=True):
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
    # The streak is per PASS, and deliberately so: pass 1 is curl-only, so its
    # verdict is not final and pass 2 re-tries the same domains with a browser.
    # The bound is therefore two streaks, not one -- but still nowhere near the
    # 20 configured domains, which is what this guards against.
    per_pass_cap = orchestrator.MAX_CONSECUTIVE_EMPTY_DOMAINS + 1
    assert len(visited) <= 2 * per_pass_cap, (
        f"walked {len(visited)} dead domains; the diminishing-returns stop did not fire"
    )
    assert len(visited) < 20, "walked the whole configured list"


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


# ---------------------------------------------------------------------------
# TWO-PASS DISCOVERY.
#
# Pass 1 sweeps every domain with curl only; pass 2 revisits what is left with
# Playwright allowed. The trap is that pass 1's verdict looks authoritative when
# it is not: on a JS storefront curl gets an unrendered shell, and every shell's
# nav menu lists brand names -- so "brand present, model absent" reads as proof
# the shop does not stock it. Retiring the domain on that basis excludes exactly
# the sites pass 2 exists for. Measured before the fix: 4 such domains, pass 2
# made ZERO fetches, product failed as source_unreachable.
# ---------------------------------------------------------------------------


# An unrendered SPA shell: no catalogue, but the nav lists brands (all of them do).
_JS_SHELL = "WestPoint | Home | Brands: WestPoint Dawlance Haier | Cart " * 40


@pytest.mark.asyncio
async def test_js_only_domains_are_retried_with_the_browser_in_pass_2(monkeypatch, _noop_template):
    """
    REGRESSION. Every configured domain is JS-rendered, so pass 1 can resolve
    none of them. Pass 2 must still run -- previously all four were marked
    settled from pass 1 and the browser was never used.
    """
    pass1, pass2 = [], []
    monkeypatch.setattr(orchestrator, "resolve_sources", _domains(
        *[(f"js{i}.pk", "trusted_secondary") for i in range(4)]
    ))

    async def fake_scrape(url, model_number="", allow_tier2=True):
        if allow_tier2:
            pass2.append(url)
            return _stocked(url)          # the browser renders it fine
        pass1.append(url)
        return _result(url, _JS_SHELL)    # curl sees only the shell

    monkeypatch.setattr(orchestrator, "smart_fetch", fake_scrape)

    result = await orchestrator.scrape_product("WestPoint", "WF-6807")

    assert pass2, "pass 2 never ran -- curl-only verdicts are being treated as final"
    assert result.get("scraped_data"), f"no sources despite {len(pass2)} browser fetches"


@pytest.mark.asyncio
async def test_pass_1_never_launches_the_browser(monkeypatch, _noop_template):
    """The whole point of pass 1: sweep cheaply. If any fetch in it is allowed to
    use Playwright, the two-pass split buys nothing."""
    flags: list[bool] = []
    monkeypatch.setattr(orchestrator, "resolve_sources", _domains(
        ("brand.pk", "official"), ("shopA.pk", "trusted_secondary"),
    ))

    async def fake_scrape(url, model_number="", allow_tier2=True):
        flags.append(allow_tier2)
        return _stocked(url)

    monkeypatch.setattr(orchestrator, "smart_fetch", fake_scrape)
    await orchestrator.scrape_product("WestPoint", "WF-6807")

    assert flags, "no fetches happened at all"
    assert not any(flags), "pass 1 allowed Playwright; it must sweep with curl only"


@pytest.mark.asyncio
async def test_a_domain_that_delivered_is_not_rescraped_in_pass_2(monkeypatch, _noop_template):
    """A domain that already gave a source is genuinely settled -- paying for a
    browser to fetch it again would be pure waste."""
    seen: list[tuple[str, bool]] = []
    monkeypatch.setattr(orchestrator, "resolve_sources", _domains(
        ("good.pk", "trusted_secondary"),
        *[(f"js{i}.pk", "trusted_secondary") for i in range(3)],
    ))

    async def fake_scrape(url, model_number="", allow_tier2=True):
        seen.append((url, allow_tier2))
        return _stocked(url) if "good.pk" in url else _result(url, _JS_SHELL)

    monkeypatch.setattr(orchestrator, "smart_fetch", fake_scrape)
    await orchestrator.scrape_product("WestPoint", "WF-6807")

    assert not any("good.pk" in u and tier2 for u, tier2 in seen), \
        "re-scraped a domain that had already delivered"


# --- Out-of-stock on the official site (2026-08-09, owner-reported) --------

@pytest.fixture
def one_official_source(monkeypatch):
    async def sources(_brand, _model, **_kw):
        return [{"url": "https://brand.pk/search?q=x", "source_type": "official",
                 "domain": "brand.pk"}]

    async def noop(*_a, **_k):
        return None

    monkeypatch.setattr(orchestrator, "resolve_sources", sources)
    monkeypatch.setattr(orchestrator, "remember_working_template", noop)


@pytest.mark.asyncio
async def test_official_out_of_stock_product_is_found_via_google_site_search(
    one_official_source, monkeypatch
):
    """
    THE OWNER-REPORTED BUG: a product genuinely live on the brand's official
    site was not found. Root cause: the site's own on-site search excludes
    out-of-stock items, so the search page mentions the brand ("Anex") but
    never the model -- and the existing bail-out logic reads that as proof
    the domain doesn't stock it. The Google site-search fallback must catch
    this for an OFFICIAL domain and still find the product.
    """
    async def fake_scrape(url, model_number="", allow_tier2=True):
        if url == "https://brand.pk/search?q=x":
            # Search widget: brand appears (nav/header), model does not --
            # the out-of-stock filtering signature.
            return _result(url, "Anex Pakistan -- browse our full range.")
        if url == "https://brand.pk/products/ag-01":
            # The real, direct product page Google still has indexed.
            return _result(url, "Anex AG-01 Handy Pull Chopper. Out of stock.")
        raise AssertionError(f"unexpected fetch: {url}")

    monkeypatch.setattr(orchestrator, "smart_fetch", fake_scrape)
    monkeypatch.setattr(orchestrator.google_search_client, "api_key", "k")
    monkeypatch.setattr(orchestrator.google_search_client, "cx", "c")

    async def fake_search(query):
        assert "site:brand.pk" in query
        assert "AG-01" in query
        return ["https://brand.pk/products/ag-01"]

    monkeypatch.setattr(orchestrator.google_search_client, "search", fake_search)

    result = await orchestrator.scrape_product("Anex", "AG-01")

    assert "failure" not in result
    assert len(result["scraped_data"]) == 1
    assert result["scraped_data"][0]["source_type"] == "official"
    assert "AG-01" in result["scraped_data"][0]["content"]


@pytest.mark.asyncio
async def test_retailer_domain_does_not_get_the_out_of_stock_fallback(monkeypatch):
    """
    Scoped to official domains ONLY (owner-directed): the same "brand
    appears, model doesn't" situation on a TRUSTED_SECONDARY (retailer)
    domain must NOT trigger the Google fallback -- it should fail exactly
    as before this change.
    """
    async def sources(_brand, _model, **_kw):
        return [{"url": "https://retailer.pk/search?q=x", "source_type": "trusted_secondary",
                 "domain": "retailer.pk"}]

    async def noop(*_a, **_k):
        return None

    monkeypatch.setattr(orchestrator, "resolve_sources", sources)
    monkeypatch.setattr(orchestrator, "remember_working_template", noop)

    search_called = False

    async def fake_search(query):
        nonlocal search_called
        search_called = True
        return ["https://retailer.pk/products/ag-01"]

    async def fake_scrape(url, model_number="", allow_tier2=True):
        return _result(url, "Anex Pakistan -- browse our full range.")

    monkeypatch.setattr(orchestrator, "smart_fetch", fake_scrape)
    monkeypatch.setattr(orchestrator.google_search_client, "api_key", "k")
    monkeypatch.setattr(orchestrator.google_search_client, "cx", "c")
    monkeypatch.setattr(orchestrator.google_search_client, "search", fake_search)

    result = await orchestrator.scrape_product("Anex", "AG-01")

    assert "failure" in result
    assert not search_called, "the out-of-stock fallback must never fire for a non-official domain"


@pytest.mark.asyncio
async def test_out_of_stock_fallback_is_a_noop_when_google_search_not_configured(
    one_official_source, monkeypatch
):
    """Optional by design, same as every other Google-search use in this
    codebase: with no key configured, discovery behaves exactly as before."""
    async def fake_scrape(url, model_number="", allow_tier2=True):
        return _result(url, "Anex Pakistan -- browse our full range.")

    monkeypatch.setattr(orchestrator, "smart_fetch", fake_scrape)
    monkeypatch.setattr(orchestrator.google_search_client, "api_key", None)
    monkeypatch.setattr(orchestrator.google_search_client, "cx", None)

    result = await orchestrator.scrape_product("Anex", "AG-01")

    assert "failure" in result
    assert result["failure"].category == "source_unreachable"


# --- WooCommerce Store API fallback (no key needed) -------------------------

class _FakeResponse:
    def __init__(self, status_code: int, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


class _FakeHttpxClient:
    def __init__(self, response: "_FakeResponse", *, raises: Exception | None = None):
        self._response = response
        self._raises = raises

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url, **kwargs):
        if self._raises:
            raise self._raises
        return self._response


@pytest.mark.asyncio
async def test_woocommerce_store_api_finds_an_out_of_stock_product(monkeypatch):
    """
    No key needed, works today. The Store API returns the product with
    is_in_stock=False -- WooCommerce's "hide out of stock" setting only
    affects the theme's own search/catalog templates, not this endpoint.
    """
    payload = [{
        "name": "Anex AG-01 Handy Pull Chopper",
        "sku": "AG-01",
        "permalink": "https://anex.pk/product/ag-01/",
        "short_description": "<p>Manual food chopper.</p>",
        "description": "<p>Easy to use. Chops onion, tomato.</p>",
        "is_in_stock": False,
    }]
    monkeypatch.setattr(
        orchestrator.httpx, "AsyncClient",
        lambda **kw: _FakeHttpxClient(_FakeResponse(200, payload)),
    )

    result = await orchestrator._woocommerce_store_api_fallback("anex.pk", "AG-01")

    assert result is not None
    assert result["source_type"] == "official"
    assert result["url"] == "https://anex.pk/product/ag-01/"
    assert "Manual food chopper" in result["content"]
    assert "<p>" not in result["content"], "HTML must be stripped, not passed through raw"


@pytest.mark.asyncio
async def test_woocommerce_store_api_returns_none_for_a_non_matching_product(monkeypatch):
    payload = [{
        "name": "Anex AG-99 Different Chopper", "sku": "AG-99",
        "permalink": "https://anex.pk/product/ag-99/",
        "short_description": "", "description": "", "is_in_stock": True,
    }]
    monkeypatch.setattr(
        orchestrator.httpx, "AsyncClient",
        lambda **kw: _FakeHttpxClient(_FakeResponse(200, payload)),
    )

    result = await orchestrator._woocommerce_store_api_fallback("anex.pk", "AG-01")
    assert result is None


@pytest.mark.asyncio
async def test_woocommerce_store_api_fails_gracefully_on_non_woocommerce_site(monkeypatch):
    """A site that isn't WooCommerce (404, or not JSON, or network error) must
    fail silently -- never raise, never break the surrounding discovery loop."""
    monkeypatch.setattr(
        orchestrator.httpx, "AsyncClient",
        lambda **kw: _FakeHttpxClient(_FakeResponse(404, {})),
    )
    assert await orchestrator._woocommerce_store_api_fallback("shopify-store.pk", "AG-01") is None

    monkeypatch.setattr(
        orchestrator.httpx, "AsyncClient",
        lambda **kw: _FakeHttpxClient(None, raises=httpx.ConnectError("boom")),
    )
    assert await orchestrator._woocommerce_store_api_fallback("dead-site.pk", "AG-01") is None


@pytest.mark.asyncio
async def test_official_fallback_tries_woocommerce_before_google(
    one_official_source, monkeypatch
):
    """WooCommerce (no key) must be tried BEFORE Google (needs a key) -- if
    WooCommerce already found it, Google must never even be called."""
    payload = [{
        "name": "Anex AG-01 Handy Pull Chopper", "sku": "AG-01",
        "permalink": "https://brand.pk/product/ag-01/",
        "short_description": "Manual chopper.", "description": "",
        "is_in_stock": False,
    }]
    monkeypatch.setattr(
        orchestrator.httpx, "AsyncClient",
        lambda **kw: _FakeHttpxClient(_FakeResponse(200, payload)),
    )

    google_called = False

    async def fake_search(query):
        nonlocal google_called
        google_called = True
        return []

    monkeypatch.setattr(orchestrator.google_search_client, "api_key", "k")
    monkeypatch.setattr(orchestrator.google_search_client, "cx", "c")
    monkeypatch.setattr(orchestrator.google_search_client, "search", fake_search)

    async def fake_scrape(url, model_number="", allow_tier2=True):
        return _result(url, "Anex Pakistan -- browse our full range.")

    monkeypatch.setattr(orchestrator, "smart_fetch", fake_scrape)

    result = await orchestrator.scrape_product("Anex", "AG-01")

    assert "failure" not in result
    assert result["scraped_data"][0]["url"] == "https://brand.pk/product/ag-01/"
    assert not google_called, "Google must not be called once WooCommerce already found it"


# --- Shopify predictive search fallback (no key needed) ---------------------

@pytest.mark.asyncio
async def test_shopify_predictive_search_finds_an_out_of_stock_product(monkeypatch):
    """
    The fix is the `unavailable_products=show` query parameter -- without
    it, Shopify's predictive search excludes sold-out products by default,
    same blind spot as the theme's visible search box.
    """
    payload = {
        "resources": {"results": {"products": [{
            "title": "Anex AG-01 Handy Pull Chopper",
            "handle": "anex-ag-01-handy-pull-chopper",
            "url": "/products/anex-ag-01-handy-pull-chopper",
            "body": "<p>Manual food chopper. Chops onion, tomato.</p>",
            "available": False,
        }]}}
    }
    captured_url = {}

    class _CapturingClient(_FakeHttpxClient):
        async def get(self, url, **kwargs):
            captured_url["url"] = url
            return await super().get(url, **kwargs)

    monkeypatch.setattr(
        orchestrator.httpx, "AsyncClient",
        lambda **kw: _CapturingClient(_FakeResponse(200, payload)),
    )

    result = await orchestrator._shopify_predictive_search_fallback("brandstore.pk", "AG-01")

    assert result is not None
    assert result["source_type"] == "official"
    assert result["url"] == "https://brandstore.pk/products/anex-ag-01-handy-pull-chopper"
    assert "Manual food chopper" in result["content"]
    assert "[unavailable_products]=show" in captured_url["url"], (
        "the documented Shopify parameter that includes sold-out products must be sent"
    )


@pytest.mark.asyncio
async def test_shopify_predictive_search_returns_none_for_a_non_matching_product(monkeypatch):
    payload = {"resources": {"results": {"products": [{
        "title": "Anex AG-99 Different Chopper", "handle": "ag-99",
        "url": "/products/ag-99", "body": "", "available": True,
    }]}}}
    monkeypatch.setattr(
        orchestrator.httpx, "AsyncClient",
        lambda **kw: _FakeHttpxClient(_FakeResponse(200, payload)),
    )

    result = await orchestrator._shopify_predictive_search_fallback("brandstore.pk", "AG-01")
    assert result is None


@pytest.mark.asyncio
async def test_shopify_predictive_search_fails_gracefully_on_non_shopify_site(monkeypatch):
    monkeypatch.setattr(
        orchestrator.httpx, "AsyncClient",
        lambda **kw: _FakeHttpxClient(_FakeResponse(404, {})),
    )
    assert await orchestrator._shopify_predictive_search_fallback("woo-store.pk", "AG-01") is None

    monkeypatch.setattr(
        orchestrator.httpx, "AsyncClient",
        lambda **kw: _FakeHttpxClient(None, raises=httpx.ConnectError("boom")),
    )
    assert await orchestrator._shopify_predictive_search_fallback("dead-site.pk", "AG-01") is None


@pytest.mark.asyncio
async def test_official_fallback_tries_shopify_when_woocommerce_finds_nothing(
    one_official_source, monkeypatch
):
    """WooCommerce endpoint 404s (not a WooCommerce site) -> falls through to
    Shopify, which finds it -- proving the two-platform chain actually
    chains, not just tries the first and gives up."""
    call_urls = []

    async def routed_get(self, url, **kwargs):
        call_urls.append(url)
        if "wp-json/wc/store" in url:
            return _FakeResponse(404, {})
        return _FakeResponse(200, {"resources": {"results": {"products": [{
            "title": "Anex AG-01 Handy Pull Chopper", "handle": "ag-01",
            "url": "/products/ag-01", "body": "Manual chopper.", "available": False,
        }]}}})

    class _RoutingClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        get = routed_get

    monkeypatch.setattr(orchestrator.httpx, "AsyncClient", lambda **kw: _RoutingClient())

    async def fake_scrape(url, model_number="", allow_tier2=True):
        return _result(url, "Anex Pakistan -- browse our full range.")

    monkeypatch.setattr(orchestrator, "smart_fetch", fake_scrape)
    monkeypatch.setattr(orchestrator.google_search_client, "api_key", None)
    monkeypatch.setattr(orchestrator.google_search_client, "cx", None)

    result = await orchestrator.scrape_product("Anex", "AG-01")

    assert "failure" not in result
    assert result["scraped_data"][0]["url"] == "https://brand.pk/products/ag-01"
    assert any("wp-json/wc/store" in u for u in call_urls), "WooCommerce must be tried first"
    assert any("search/suggest.json" in u for u in call_urls), "Shopify must be tried after WooCommerce fails"
