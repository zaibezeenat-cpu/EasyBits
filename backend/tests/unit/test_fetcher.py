"""
Tiered fetch: curl_cffi (Tier 1, fast TLS impersonation) -> Playwright+stealth
(Tier 2, JS render). These lock the cascade decisions without any network:
Tier 1 is used only when it returns real product content; a block page, an empty
JS shell (model missing), or curl being unavailable all escalate to Playwright.
"""
from unittest.mock import AsyncMock

import pytest

from app.scraping import fetcher
from app.scraping.models import ScrapeResult


def _r(
    content: str,
    *,
    success: bool = True,
    engine: str = "curl_cffi",
    product_links: list[str] | None = None,
) -> ScrapeResult:
    return ScrapeResult(
        url="https://x.pk/p",
        content=content,
        engine_used=engine,
        success=success,
        product_links=product_links or [],
    )


# A storefront page's worth of real text, long enough to clear the rendered-content
# floor. Used to prove that LENGTH ALONE never decides the escalation.
_BULK = ("Free delivery across Pakistan. Installments available. Customer care. " * 40)
assert len(_BULK) >= fetcher._RENDERED_CONTENT_FLOOR_CHARS


@pytest.mark.asyncio
async def test_tier1_usable_returns_curl_and_skips_playwright(monkeypatch):
    monkeypatch.setattr(fetcher, "_fetch_with_curl",
                        AsyncMock(return_value=_r("Deluxe Hair Straightener WF-6807 35 Watts 2 Years Warranty")))
    pw = AsyncMock()
    monkeypatch.setattr(fetcher, "scrape_with_playwright", pw)

    result = await fetcher.smart_fetch("https://x.pk/p", "WF-6807")

    assert result.engine_used == "curl_cffi"
    pw.assert_not_called()


@pytest.mark.asyncio
async def test_tier1_block_page_escalates_to_playwright(monkeypatch):
    monkeypatch.setattr(fetcher, "_fetch_with_curl",
                        AsyncMock(return_value=_r("Just a moment...\nEnable JavaScript and cookies to continue")))
    pw = AsyncMock(return_value=_r("WF-6807 real specs", engine="playwright"))
    monkeypatch.setattr(fetcher, "scrape_with_playwright", pw)

    result = await fetcher.smart_fetch("https://x.pk/p", "WF-6807")

    pw.assert_awaited_once()
    assert result.engine_used == "playwright"


@pytest.mark.asyncio
async def test_tier1_empty_shell_model_missing_escalates(monkeypatch):
    # 200 OK but the model is absent (JS-rendered shell) -- the "secret sauce".
    monkeypatch.setattr(fetcher, "_fetch_with_curl",
                        AsyncMock(return_value=_r("<div id=root></div> loading store front")))
    pw = AsyncMock(return_value=_r("WF-6807 rendered specs", engine="playwright"))
    monkeypatch.setattr(fetcher, "scrape_with_playwright", pw)

    result = await fetcher.smart_fetch("https://x.pk/p", "WF-6807")

    pw.assert_awaited_once()
    assert result.engine_used == "playwright"


@pytest.mark.asyncio
async def test_tier1_unavailable_escalates_to_playwright(monkeypatch):
    # curl_cffi not installed / request failed -> _fetch_with_curl returns None.
    monkeypatch.setattr(fetcher, "_fetch_with_curl", AsyncMock(return_value=None))
    pw = AsyncMock(return_value=_r("WF-6807 specs", engine="playwright"))
    monkeypatch.setattr(fetcher, "scrape_with_playwright", pw)

    result = await fetcher.smart_fetch("https://x.pk/p", "WF-6807")

    pw.assert_awaited_once()
    assert result.engine_used == "playwright"


@pytest.mark.asyncio
async def test_no_model_number_accepts_nonblock_content(monkeypatch):
    # Following a category page: no model to match -> mention check skipped.
    monkeypatch.setattr(fetcher, "_fetch_with_curl",
                        AsyncMock(return_value=_r("Category listing of appliances and prices")))
    pw = AsyncMock()
    monkeypatch.setattr(fetcher, "scrape_with_playwright", pw)

    result = await fetcher.smart_fetch("https://x.pk/category", "")

    assert result.engine_used == "curl_cffi"
    pw.assert_not_called()


@pytest.mark.asyncio
async def test_no_model_number_block_page_still_escalates(monkeypatch):
    # Even without a model, a block page must not be accepted.
    monkeypatch.setattr(fetcher, "_fetch_with_curl",
                        AsyncMock(return_value=_r("Attention Required! | Cloudflare")))
    pw = AsyncMock(return_value=_r("real category page", engine="playwright"))
    monkeypatch.setattr(fetcher, "scrape_with_playwright", pw)

    await fetcher.smart_fetch("https://x.pk/category", "")

    pw.assert_awaited_once()


# ---------------------------------------------------------------------------
# Tier-1 acceptance when the model number is ABSENT.
#
# This is the split that removed ~79% of pipeline runtime: a shop that does not
# stock the product returns a good page that simply never names the model, and
# launching a browser to re-confirm that costs seconds and proves nothing. The
# tests below pin BOTH directions, because the failure modes are asymmetric --
# a wrong "escalate" costs speed, a wrong "accept" loses a real source.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_soft_404_with_product_grid_does_not_escalate(monkeypatch):
    """
    The 'Product Not Found' page that still renders a recommended-products grid.

    It is large and names the brand, so a length-or-brand heuristic would treat it
    as suspicious. It is in fact the single most common case in a 105-source run,
    and it is CONCLUSIVE: the site rendered, and our model is not there. Accepting
    it is both correct and free -- Playwright would fetch the identical page.
    """
    monkeypatch.setattr(
        fetcher, "_fetch_with_curl",
        AsyncMock(return_value=_r(
            "Sorry, we could not find that product. WestPoint bestsellers: " + _BULK,
            product_links=["https://x.pk/products/westpoint-wf-1000",
                           "https://x.pk/products/westpoint-wf-2000"],
        )),
    )
    pw = AsyncMock()
    monkeypatch.setattr(fetcher, "scrape_with_playwright", pw)

    result = await fetcher.smart_fetch("https://x.pk/search?q=WF-6807", "WF-6807")

    pw.assert_not_called()
    assert result.engine_used == "curl_cffi"
    assert result.metadata["fetch_reason"] == "rendered_without_match"


@pytest.mark.asyncio
async def test_js_shell_with_long_boilerplate_still_escalates(monkeypatch):
    """
    THE REAL HAZARD, and why character count cannot be the primary signal.

    An unrendered SPA still ships nav, footer, cookie banner and marketing copy,
    so it clears any length floor comfortably. What it does NOT have is product
    links -- the catalogue has not been injected yet. Accepting this page would
    silently discard a source that genuinely carries the product.
    """
    monkeypatch.setattr(
        fetcher, "_fetch_with_curl",
        AsyncMock(return_value=_r(_BULK, product_links=[])),
    )
    pw = AsyncMock(return_value=_r("WF-6807 rendered specs", engine="playwright"))
    monkeypatch.setattr(fetcher, "scrape_with_playwright", pw)

    result = await fetcher.smart_fetch("https://x.pk/search?q=WF-6807", "WF-6807")

    pw.assert_awaited_once()
    assert result.engine_used == "playwright"
    assert result.metadata["fetch_reason"] == "no_product_links"


@pytest.mark.asyncio
async def test_explicit_no_results_short_page_does_not_escalate(monkeypatch):
    """An explicit 'no products found' proves the site's search ran. Conclusive
    on its own, so a short page must not cost a browser."""
    monkeypatch.setattr(
        fetcher, "_fetch_with_curl",
        AsyncMock(return_value=_r("No products found matching your search.")),
    )
    pw = AsyncMock()
    monkeypatch.setattr(fetcher, "scrape_with_playwright", pw)

    result = await fetcher.smart_fetch("https://x.pk/search?q=WF-6807", "WF-6807")

    pw.assert_not_called()
    assert result.metadata["fetch_reason"] == "explicit_no_results"


@pytest.mark.asyncio
async def test_rendered_page_below_length_floor_escalates(monkeypatch):
    """A near-empty page carrying one stray link must not pass as 'rendered' --
    the length floor is the backstop for exactly this."""
    monkeypatch.setattr(
        fetcher, "_fetch_with_curl",
        AsyncMock(return_value=_r("loading…", product_links=["https://x.pk/products/a"])),
    )
    pw = AsyncMock(return_value=_r("WF-6807 specs", engine="playwright"))
    monkeypatch.setattr(fetcher, "scrape_with_playwright", pw)

    result = await fetcher.smart_fetch("https://x.pk/search?q=WF-6807", "WF-6807")

    pw.assert_awaited_once()
    assert result.metadata["fetch_reason"] == "content_below_floor"


@pytest.mark.asyncio
async def test_model_found_is_still_the_cheapest_path(monkeypatch):
    """The happy path must remain untouched: model present -> Tier 1, no browser."""
    monkeypatch.setattr(
        fetcher, "_fetch_with_curl",
        AsyncMock(return_value=_r("WestPoint WF-6807 Deluxe Hair Straightener 35W")),
    )
    pw = AsyncMock()
    monkeypatch.setattr(fetcher, "scrape_with_playwright", pw)

    result = await fetcher.smart_fetch("https://x.pk/p", "WF-6807")

    pw.assert_not_called()
    assert result.metadata["fetch_reason"] == "model_found"
    assert result.metadata["fetch_tier"] == 1


@pytest.mark.asyncio
async def test_escalation_records_both_tier_timings(monkeypatch):
    """Stage 0 instrumentation: an escalated fetch must report BOTH tiers' cost,
    otherwise the benchmark cannot attribute where the time went."""
    monkeypatch.setattr(fetcher, "_fetch_with_curl", AsyncMock(return_value=None))
    monkeypatch.setattr(
        fetcher, "scrape_with_playwright",
        AsyncMock(return_value=_r("WF-6807 specs", engine="playwright")),
    )

    result = await fetcher.smart_fetch("https://x.pk/p", "WF-6807")

    assert result.metadata["fetch_tier"] == 2
    assert result.metadata["fetch_reason"] == "tier1_unavailable"
    assert "fetch_tier1_ms" in result.metadata
    assert "fetch_tier2_ms" in result.metadata


# --- Overall per-URL deadline (2026-08-09, "why the delay even in strict mode") ---

@pytest.mark.asyncio
async def test_smart_fetch_times_out_at_the_configured_overall_deadline(monkeypatch):
    """
    Before this, ONE url had no combined cap -- curl's own timeout plus
    Playwright's (attempts x per-attempt timeout) could add up to 150s with
    no ceiling. smart_fetch must now bail at SCRAPE_TIMEOUT_SECONDS and
    return a normal failed ScrapeResult, not hang or raise.
    """
    import asyncio

    monkeypatch.setattr(fetcher.settings, "SCRAPE_TIMEOUT_SECONDS", 0.05)

    async def _hangs_forever(*args, **kwargs):
        await asyncio.sleep(10)
        return _r("never gets here")

    monkeypatch.setattr(fetcher, "_fetch_with_curl", _hangs_forever)

    result = await fetcher.smart_fetch("https://slow.pk/p", "WF-6807")

    assert result.success is False
    assert result.metadata["fetch_reason"] == "overall_timeout"
    assert result.error_message is not None
    assert "0.05" in result.error_message


@pytest.mark.asyncio
async def test_smart_fetch_well_under_the_deadline_is_unaffected(monkeypatch):
    """A normal fast fetch must not be touched by the deadline wrapper at all."""
    monkeypatch.setattr(fetcher.settings, "SCRAPE_TIMEOUT_SECONDS", 5.0)
    monkeypatch.setattr(fetcher, "_fetch_with_curl",
                        AsyncMock(return_value=_r("WF-6807 in stock, 35 Watts")))

    result = await fetcher.smart_fetch("https://fast.pk/p", "WF-6807")

    assert result.success is True
    assert result.metadata["fetch_tier"] == 1


@pytest.mark.asyncio
async def test_curl_fetch_uses_the_configured_timeout_not_a_hardcoded_30(monkeypatch):
    """CURL_FETCH_TIMEOUT_SECONDS (default 15, down from a hardcoded 30) must
    actually reach curl_cffi's request call."""
    captured_kwargs = {}

    class _FakeResponse:
        text = "WF-6807 specs, 35 Watts"

    class _FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def get(self, url, **kwargs):
            captured_kwargs.update(kwargs)
            return _FakeResponse()

    fake_curl_cffi = type("_M", (), {"requests": type("_R", (), {"AsyncSession": _FakeSession})})
    monkeypatch.setitem(__import__("sys").modules, "curl_cffi", fake_curl_cffi)
    monkeypatch.setitem(__import__("sys").modules, "curl_cffi.requests", fake_curl_cffi.requests)
    monkeypatch.setattr(fetcher.settings, "CURL_FETCH_TIMEOUT_SECONDS", 12.5)

    await fetcher._fetch_with_curl("https://x.pk/p", "WF-6807")

    assert captured_kwargs["timeout"] == 12.5
