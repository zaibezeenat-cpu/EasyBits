"""
Tiered fetch: curl_cffi (Tier 1, fast TLS impersonation) -> Playwright+stealth
(Tier 2, JS render). These lock the cascade decisions without any network:
Tier 1 is used only when it returns real product content; a block page, an empty
JS shell (model missing), or curl being unavailable all escalate to Playwright.
"""
import pytest
from unittest.mock import AsyncMock

from app.scraping import fetcher
from app.scraping.models import ScrapeResult


def _r(content: str, *, success: bool = True, engine: str = "curl_cffi") -> ScrapeResult:
    return ScrapeResult(url="https://x.pk/p", content=content, engine_used=engine, success=success)


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
