"""
Tiered page fetch — the single entry point for getting a URL's HTML.

    Tier 1  curl_cffi (real Chrome TLS/JA3 impersonation) -- fast, no browser,
            defeats passive fingerprinting (Cloudflare Bot-Fight, UA checks).
    Tier 2  Playwright + stealth -- renders JavaScript, for SPA pages and dynamic
            checks Tier 1 cannot handle.
    Tier 3  (outside this module) operator-provided Details -- when both fail, the
            orchestrator escalates and the pasted Details are used.

Tier 1 is used ONLY when it returns real product content. A block page, an empty
JS shell (the model never appears), or curl_cffi being unavailable all fall
through to Tier 2. Hard interactive challenges (Cloudflare Turnstile) survive both
and correctly end at Tier 3 by design.
"""
import logging

from app.scraping.models import ScrapeResult
from app.scraping.playwright_client import (
    _clean_html_to_text,
    extract_candidate_titles,
    extract_product_links,
    is_block_page,
    scrape_with_playwright,
)
from app.scraping.source_discovery import search_result_mentions_product

logger = logging.getLogger(__name__)


async def _fetch_with_curl(url: str, model_number: str = "") -> ScrapeResult | None:
    """Tier 1 fetch via curl_cffi with real-Chrome TLS/JA3 impersonation.

    Args:
        url: The page to fetch.
        model_number: Used to extract product links/titles from the HTML.

    Returns:
        A ScrapeResult on success, or None when curl_cffi is not installed or the
        request fails -- so the caller falls through to Playwright. Never raises.
    """
    try:
        from curl_cffi.requests import AsyncSession
    except ImportError:
        return None

    try:
        async with AsyncSession() as session:
            # allow_redirects is on by default; set explicitly so HTTP->HTTPS
            # 301/302 always follow. impersonate mimics real Chrome's TLS/JA3.
            response = await session.get(
                url, impersonate="chrome", timeout=30, allow_redirects=True
            )
        html = response.text
    except Exception as e:
        logger.warning(f"curl_cffi fetch failed for {url}: {e}")
        return None

    if not html:
        return None

    return ScrapeResult(
        url=url,
        content=_clean_html_to_text(html),
        engine_used="curl_cffi",
        success=True,
        product_links=extract_product_links(html, url, model_number) if model_number else [],
        candidate_titles=extract_candidate_titles(html, model_number) if model_number else [],
    )


def _tier1_usable(result: ScrapeResult | None, model_number: str) -> bool:
    """Whether a Tier-1 result is good enough to skip the browser.

    Usable means: present, successful, non-empty content, NOT an anti-bot page,
    and -- when a model is given -- the content actually names the model. That last
    clause catches a 200-OK empty JS shell that must escalate to Tier 2 rather than
    be read as "no facts". With no model_number (e.g. following a category page) a
    non-empty, non-block page is enough.
    """
    if result is None or not result.success or not result.content.strip():
        return False
    if is_block_page(result.content):
        return False
    if model_number:
        return search_result_mentions_product(result.content, model_number)
    return True


async def smart_fetch(url: str, model_number: str = "") -> ScrapeResult:
    """Fetch a URL with the cheapest engine that works (Tier 1 -> Tier 2).

    The caller (orchestrator) still applies its own block/mention/follow logic on
    the returned result, so a still-blocked Tier-2 result flows through to the
    source_blocked / operator-Details fallback unchanged.
    """
    tier1 = await _fetch_with_curl(url, model_number)
    if _tier1_usable(tier1, model_number):
        logger.debug(f"Tier 1 (curl_cffi) served {url}")
        return tier1  # not None: _tier1_usable guarantees it

    logger.info(f"Tier 1 insufficient for {url}; escalating to Playwright (Tier 2).")
    return await scrape_with_playwright(url, model_number)
