"""
Tiered page fetch — the single entry point for getting a URL's HTML.

    Tier 1  curl_cffi (real Chrome TLS/JA3 impersonation) -- fast, no browser,
            defeats passive fingerprinting (Cloudflare Bot-Fight, UA checks).
    Tier 2  Playwright + stealth -- renders JavaScript, for SPA pages and dynamic
            checks Tier 1 cannot handle.
    Tier 3  (outside this module) operator-provided Details -- when both fail, the
            orchestrator escalates and the pasted Details are used.

WHY THE TIER-1 ACCEPTANCE RULE IS NOT JUST "DOES THE PAGE NAME THE MODEL"
------------------------------------------------------------------------
It used to be exactly that, and it was the single biggest cost in the pipeline.
A shop that simply DOES NOT STOCK the product returns a perfectly good,
fully-rendered page that just never names the model. The old rule read that as
"Tier 1 failed" and launched a whole Chromium browser to re-confirm a "not
found" that curl had already answered correctly.

With 105+ configured sources and a product carried by only 3-5 of them, roughly
20 of the 25 permitted scrape attempts per product were exactly this case --
each paying a full browser launch. Measured: ~150s/product with discovery vs
~32s/product with discovery disabled, i.e. ~79% of runtime spent proving
absences the cheap fetch had already proven.

So a missing model number is now split into two very different situations:

  * the page RENDERED and genuinely lacks the product  -> trust it, no browser
  * the page is an EMPTY JS SHELL that renders later   -> escalate, browser needed

`_tier1_decision` below is that split, and it errs toward escalating: a wrong
"escalate" costs a few seconds, a wrong "accept" loses a real source and can
push a product into Manual Review.
"""
import asyncio
import logging
import time
from typing import NamedTuple

from app.core.config import settings
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

# Cleaned-text length below which a page is treated as too thin to have really
# rendered. Deliberately a BACKSTOP, not the primary signal: character count says
# nothing about whether the catalogue rendered, and a JS shell's nav + footer +
# cookie banner + marketing copy can easily clear any threshold on its own. The
# primary signal is whether product links are present (see _tier1_decision).
_RENDERED_CONTENT_FLOOR_CHARS = 1500

# Phrases an empty search-results page uses. Only ever consulted once the model
# number is ALREADY known to be absent from the content, so the page is known not
# to be our product either way -- these merely upgrade "probably not stocked" to
# "definitely not stocked", letting us skip the browser even on a short page.
_NO_RESULTS_MARKERS = (
    "no products found",
    "no products were found",
    "no matching products",
    "no results found",
    "no result found",
    "0 results",
    "nothing matched",
    "your search did not match",
    "sorry, no products",
    "try searching for",
    "no products match",
)


class Tier1Decision(NamedTuple):
    """Whether the cheap fetch is good enough, and why -- the reason string is
    what makes the escalation mix visible in the logs."""

    usable: bool
    reason: str


def _has_no_results_marker(content: str) -> bool:
    lowered = (content or "").lower()
    return any(marker in lowered for marker in _NO_RESULTS_MARKERS)


def _tier1_decision(result: ScrapeResult | None, model_number: str) -> Tier1Decision:
    """
    Decide whether a Tier-1 result can be used as-is, and record why.

    The interesting branch is the last one: the model number is absent. That is
    either a real "this shop does not stock it" (usable -- the answer is correct
    and cost nothing) or an unrendered JS shell (not usable -- the browser has to
    run before we can conclude anything).

    Product links are the discriminator. A server-rendered storefront page --
    including an empty search-results page, which still renders its "you might
    also like" grid -- carries product links in the DOM. An unrendered shell
    carries none, because the catalogue has not been injected yet.
    """
    if result is None:
        return Tier1Decision(False, "tier1_unavailable")
    if not result.success:
        return Tier1Decision(False, "tier1_request_failed")
    if not result.content.strip():
        return Tier1Decision(False, "tier1_empty_body")
    if is_block_page(result.content):
        return Tier1Decision(False, "block_page")

    # No model to match against (e.g. following a category/landing page): any
    # real, non-blocked page is fine. Unchanged behaviour.
    if not model_number:
        return Tier1Decision(True, "no_model_check")

    if search_result_mentions_product(result.content, model_number):
        return Tier1Decision(True, "model_found")

    # --- The model is absent. Rendered-but-absent, or not yet rendered? ---

    # An explicit "no results" message is proof the site's search RAN and found
    # nothing. Conclusive on its own, regardless of page size.
    if _has_no_results_marker(result.content):
        return Tier1Decision(True, "explicit_no_results")

    # Product links prove the catalogue rendered server-side. Paired with the
    # length backstop so a near-empty page carrying one stray link cannot pass.
    if result.product_links and len(result.content) >= _RENDERED_CONTENT_FLOOR_CHARS:
        return Tier1Decision(True, "rendered_without_match")

    # No links: most likely an unrendered shell, so the browser has to run.
    #
    # This deliberately accepts a false positive -- a genuinely rendered "out of
    # stock" page that happens to carry NO product grid at all escalates and
    # costs a browser to reach the same conclusion. That is the safe direction
    # (costs speed, never accuracy), but it is logged under its own reason so its
    # real-world frequency is visible rather than assumed.
    if not result.product_links:
        return Tier1Decision(False, "no_product_links")

    return Tier1Decision(False, "content_below_floor")


def _tier1_usable(result: ScrapeResult | None, model_number: str) -> bool:
    """Boolean form of `_tier1_decision`, kept as the simple predicate."""
    return _tier1_decision(result, model_number).usable


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
            # timeout: settings.CURL_FETCH_TIMEOUT_SECONDS (down from a
            # hardcoded 30, 2026-08-09) -- see that setting's docstring.
            response = await session.get(
                url, impersonate="chrome",
                timeout=settings.CURL_FETCH_TIMEOUT_SECONDS,
                allow_redirects=True,
            )
        html = response.text
    except Exception as e:
        logger.warning(f"curl_cffi fetch failed for {url}: {e}")
        return None

    if not html:
        return None

    # `extract_product_links` already returns generic /product/ links even when
    # none match the model, which is exactly what `_tier1_decision` needs to tell
    # a rendered storefront from an unrendered shell -- so no change is needed
    # here. With no model number the decision short-circuits before consulting
    # links, so extracting them in that case would be pure work for nothing.
    return ScrapeResult(
        url=url,
        content=_clean_html_to_text(html),
        engine_used="curl_cffi",
        success=True,
        product_links=extract_product_links(html, url, model_number) if model_number else [],
        candidate_titles=extract_candidate_titles(html, model_number) if model_number else [],
    )


async def smart_fetch(
    url: str, model_number: str = "", allow_tier2: bool = True
) -> ScrapeResult:
    """
    Fetch a URL with the cheapest engine that works (Tier 1 -> Tier 2), bounded
    by an OVERALL wall-clock deadline (settings.SCRAPE_TIMEOUT_SECONDS,
    2026-08-09, owner-directed -- "why the delay even in strict mode").

    Before this, ONE url could take up to CURL_FETCH_TIMEOUT_SECONDS (curl) +
    PLAYWRIGHT_LOAD_ATTEMPTS x 60s (Playwright) with no combined cap -- and
    that applies even to a single operator-pasted link in
    provided_source_mode=strict, which still goes through this exact tiered
    fetch. A timeout here is treated exactly like any other failed/blocked
    fetch: the caller's existing fallback (operator Details, or simply an
    unconfirmed field since 2026-08-09's Manual Review relaxation) takes over,
    nothing raises.
    """
    try:
        return await asyncio.wait_for(
            _smart_fetch_inner(url, model_number, allow_tier2),
            timeout=settings.SCRAPE_TIMEOUT_SECONDS,
        )
    except TimeoutError:
        logger.warning(
            f"smart_fetch exceeded the {settings.SCRAPE_TIMEOUT_SECONDS}s overall "
            f"deadline for {url}; treating as a failed fetch."
        )
        return ScrapeResult(
            url=url, content="", engine_used="timeout", success=False,
            error_message=f"Exceeded overall {settings.SCRAPE_TIMEOUT_SECONDS}s fetch deadline",
            metadata={"fetch_reason": "overall_timeout"},
        )


async def _smart_fetch_inner(
    url: str, model_number: str, allow_tier2: bool
) -> ScrapeResult:
    """The actual tiered fetch; see smart_fetch's docstring for the deadline
    wrapping this. Split out so asyncio.wait_for can cancel it cleanly."""
    tier1_started = time.perf_counter()
    tier1 = await _fetch_with_curl(url, model_number)
    tier1_ms = int((time.perf_counter() - tier1_started) * 1000)

    decision = _tier1_decision(tier1, model_number)

    # `tier1 is not None` is implied by decision.usable, but tested explicitly
    # rather than asserted: `python -O` strips asserts, and the failure mode
    # would be an AttributeError deep in the caller instead of a clean fallback.
    if decision.usable and tier1 is not None:
        logger.debug(f"Tier 1 (curl_cffi) served {url} [{decision.reason}] in {tier1_ms}ms")
        tier1.metadata = {
            **tier1.metadata,
            "fetch_tier": 1,
            "fetch_tier1_ms": tier1_ms,
            "fetch_reason": decision.reason,
        }
        return tier1

    if not allow_tier2:
        # Pass 1: the browser is off limits. Hand back whatever Tier 1 got --
        # weak, but the caller only needs to learn "this domain did not answer
        # cheaply" and move on. A failed curl (tier1 is None) becomes an
        # unsuccessful result rather than silently launching a browser here,
        # which would defeat the entire point of a browser-free pass.
        logger.debug(
            f"Tier 1 insufficient for {url} [{decision.reason}] in {tier1_ms}ms; "
            f"browser not allowed this pass, deferring."
        )
        deferred = tier1 or ScrapeResult(
            url=url, content="", engine_used="curl_cffi",
            success=False, error_message=f"tier1 failed: {decision.reason}",
        )
        deferred.metadata = {
            **deferred.metadata,
            "fetch_tier": 1,
            "fetch_tier1_ms": tier1_ms,
            "fetch_reason": decision.reason,
            "fetch_deferred": True,
        }
        return deferred

    logger.info(
        f"Tier 1 insufficient for {url} [{decision.reason}] after {tier1_ms}ms; "
        f"escalating to Playwright (Tier 2)."
    )
    tier2_started = time.perf_counter()
    result = await scrape_with_playwright(url, model_number)
    tier2_ms = int((time.perf_counter() - tier2_started) * 1000)

    result.metadata = {
        **result.metadata,
        "fetch_tier": 2,
        "fetch_tier1_ms": tier1_ms,
        "fetch_tier2_ms": tier2_ms,
        "fetch_reason": decision.reason,
    }
    return result
