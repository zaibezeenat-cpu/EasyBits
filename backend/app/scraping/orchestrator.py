import asyncio
import logging
import re
from typing import Any
from urllib.parse import quote_plus, urlparse

import httpx

from app.core.config import settings
from app.models.failure import FailureInfo
from app.scraping.fetcher import smart_fetch
from app.scraping.google_search_client import google_search_client
from app.scraping.playwright_client import _clean_html_to_text, is_block_page
from app.scraping.source_discovery import (
    brand_matches_identity,
    model_matches_identity,
    remember_working_template,
    resolve_sources,
    search_result_mentions_product,
    template_of_url,
)

logger = logging.getLogger(__name__)

# Enough independent sources for strong corroboration without scraping every one
# of a large configured list. Domains are consumed in trust order, so these are
# the most authoritative available.
MAX_SOURCES_FOR_CORROBORATION = 2

# Attempt ceilings, ONE PER PASS rather than one shared budget.
#
# Discovery runs in two passes (see scrape_product): pass 1 tries every domain
# with the cheap curl fetch only, pass 2 revisits what is left with Playwright
# allowed. A single shared budget starves pass 2 -- pass 1 walks the whole list
# first, so by the time the browser is permitted the budget is gone and pass 2
# silently does nothing. Separate budgets also let each one be sized to what an
# attempt actually COSTS: a curl fetch is ~1-2s, a rendered page ~3-6s.
MAX_TIER1_ATTEMPTS = 30
MAX_TIER2_ATTEMPTS = 8

# Consecutive domains that may yield nothing before we conclude the remaining
# list is not going to produce anything either.
#
# MEASURED on a real 2-product run (WF-6807, 2026-08-03): 13 domains were tried,
# 2 produced a source and 11 produced nothing. The 2 useful ones answered in the
# first 9 seconds; the other 11 cost 128 seconds and changed no output at all --
# 93% of scrape time spent confirming absences. The configured source list is
# ordered by trust, so once several consecutive domains in that order have
# nothing, the tail almost never does either.
MAX_CONSECUTIVE_EMPTY_DOMAINS = 5

# Max concurrent curl (Tier-1) fetches in Pass 1 per product.
# Pass 1 is pure HTTP — no browser, no shared process state — so running
# domains in parallel is safe. Capped at 8 to avoid hammering retailer sites
# and to keep total concurrent sockets sane when BATCH_CONCURRENCY > 1.
# Measured speedup: 25 domains × 3s serial = 75s → ~10s parallel at 8 wide.
_PASS1_CONCURRENCY = 8


def _corroboration_satisfied(scraped_data: list[dict[str, str]]) -> bool:
    """
    True once the sources in hand can already confirm facts, so further scraping
    cannot change any answer.

    This mirrors fact_corroboration's OWN rule rather than inventing a new one:
    an OFFICIAL brand source stating a value is authoritative by itself. So with
    an official source plus one independent cross-check, every field either
    resolves now or never will -- scraping more domains only costs time.

    Why not stop at the official source ALONE: the extra source is what fills
    fields the brand's own page omits (brand sites list far less than retailers)
    and gives a second opinion where they overlap. Without it, an omitted field
    backed by nothing would escalate a product that a single retailer could have
    completed.

    The threshold is settings.MIN_SOURCES_WITH_OFFICIAL so it can be raised
    without a code change if the review queue ever grows.
    """
    if len(scraped_data) < settings.MIN_SOURCES_WITH_OFFICIAL:
        return False
    return any(doc.get("source_type") == "official" for doc in scraped_data)


async def _follow_to_detail_page(search_result, model_number: str,
                                 brand_name: str = "", require_brand_identity: bool = False,
                                 allow_tier2: bool = True):
    """
    Follows the best product link from a search page to the product detail page.

    Returns None when no detail page names the product, and that is deliberate:
    a search-results page is NOT evidence the store stocks the item. Storefronts
    echo the query back ("53 results found for KLU-12B03S") and return fuzzy
    matches, so a listing can name the model while every product on it is
    something else -- observed live, where a search for KLU-12B03S returned a
    page whose top hit was KGP-18C01S. Passing that listing to the Extractor
    would invite it to describe the wrong product with full confidence.
    Only a detail page that names the model counts as a source.

    `require_brand_identity` adds a second condition for sources whose host
    serves more than one brand (dwphome.pk carries both EcoStar and Gree): the
    detail page must identify itself as this brand in its URL slug or title.
    Applied only to those sources, because for a single-brand host it could
    only reject valid pages -- a brand that titles its own products without
    naming itself would lose its official source and escalate needlessly.
    """
    for link in search_result.product_links[:3]:
        # Pre-filter: if the URL path identifies this as a product detail page
        # (contains /products/ or /product/) but does NOT contain our model number
        # in the slug, it is unambiguously a different product -- skip the fetch.
        #
        # WHY THIS IS SAFE: Shopify and most Pakistani retailer platforms embed the
        # model code in the product slug (e.g. "westpoint-electric-oven-wf-7500"),
        # so model_matches_identity on the URL alone is conclusive for detail pages.
        # Generic slugs ("/products/item-123") have no model in the path and are
        # left through to be checked after fetch, preserving the original safety net.
        #
        # PRESERVES THE ORIGINAL TEAM'S INTENT: the KLU-12B03S/KGP-18C01S false-match
        # guard still runs for every URL that passes this pre-filter, so the
        # downstream model_matches_identity check on title+slug is unchanged.
        parsed_path = urlparse(link).path.lower()
        is_product_detail_url = "/products/" in parsed_path or "/product/" in parsed_path
        if is_product_detail_url and not model_matches_identity(model_number, link, []):
            logger.debug(
                f"Skipping {link}: URL slug identifies a different product "
                f"than {model_number} -- no fetch needed."
            )
            continue
        try:
            # Inherits the caller's pass: following a link is still a fetch, and
            # in pass 1 it must stay browser-free like every other one. Missing
            # this made pass 1 quietly launch Chromium for every detail page.
            detail = await smart_fetch(link, model_number, allow_tier2=allow_tier2)
        except Exception as e:
            logger.warning(f"Could not follow product link {link}: {e}")
            continue
        if not (detail.success and detail.content
                and search_result_mentions_product(detail.content, model_number)):
            continue
        # The page must IDENTIFY as this exact model in its title/slug, not just
        # mention it in the body -- otherwise an "HRF-316 IPRA" page that
        # cross-links the IPGA variant would be accepted and the two products'
        # specs blended (the model-suffix trap).
        if not model_matches_identity(model_number, detail.url or link, detail.candidate_titles):
            logger.info(
                f"Rejected {link}: mentions {model_number} but its title/URL is a different "
                f"model variant -- avoiding a suffix/colour mix-up."
            )
            continue
        if require_brand_identity and not brand_matches_identity(
            brand_name, detail.url or link, detail.candidate_titles
        ):
            logger.info(
                f"Rejected {link}: names {model_number} but does not identify as "
                f"'{brand_name}'. This host serves several brands, so an unmatched "
                f"page is a different brand's product, not this one."
            )
            continue
        logger.info(f"Followed search result to detail page: {link}")
        return detail
    return None


_WOOCOMMERCE_STORE_API_TIMEOUT_SECONDS = 12.0


def _normalise_for_match(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (text or "").lower())


async def _woocommerce_store_api_fallback(
    domain: str, model_number: str
) -> dict[str, Any] | None:
    """
    WooCommerce's built-in public Store REST API -- no key, no auth, enabled
    by default on essentially every WooCommerce install (it's what powers the
    theme's own cart/checkout AJAX).

    WHY THIS WORKS WHEN THE SITE'S OWN SEARCH BOX DOESN'T: "hide out of stock
    items" is a CATALOG/THEME display setting (WooCommerce Settings ->
    Products -> Inventory) -- it controls what the storefront's search
    widget and shop-page templates render, not what the underlying product
    data contains. The Store API queries WooCommerce's product data
    directly, so an out-of-stock product still comes back in the JSON with
    `is_in_stock: false`, even on a store where the theme's search box would
    never show it.

    Returns a scraped_data-shaped dict built from the API's OWN name/sku/
    description fields (no second page fetch needed -- the API already
    returns everything the Extractor needs), or None on any failure: wrong
    platform (this site isn't WooCommerce), the endpoint disabled, no
    matching product, network error. Never raises.
    """
    url = f"https://{domain}/wp-json/wc/store/v1/products?search={quote_plus(model_number)}"
    try:
        async with httpx.AsyncClient(timeout=_WOOCOMMERCE_STORE_API_TIMEOUT_SECONDS) as client:
            response = await client.get(url)
        if response.status_code != 200:
            return None
        products = response.json()
        if not isinstance(products, list):
            return None
    except Exception as e:
        logger.debug(f"WooCommerce Store API not usable on {domain}: {e}")
        return None

    needle = _normalise_for_match(model_number)
    if not needle:
        return None

    for product in products:
        name = str(product.get("name") or "")
        sku = str(product.get("sku") or "")
        permalink = str(product.get("permalink") or "")
        identity = _normalise_for_match(name) + _normalise_for_match(sku) + _normalise_for_match(permalink)
        if needle not in identity:
            continue

        # The API's own description/short_description IS the product page's
        # real copy (WooCommerce renders these verbatim on the front end),
        # so no second fetch is needed -- just strip the HTML the API
        # returns it as.
        description_html = f"{product.get('name', '')}\n{product.get('short_description', '')}\n{product.get('description', '')}"
        content = _clean_html_to_text(description_html)
        if not content.strip():
            continue

        stock_note = "in stock" if product.get("is_in_stock") else "OUT OF STOCK"
        logger.info(
            f"Found {model_number} on {domain} via the WooCommerce Store API "
            f"({stock_note}) after the site's own search excluded it."
        )
        return {
            "url": permalink or url,
            "source_type": "official",
            "content": content,
            "candidate_titles": [name] if name else [],
        }

    return None


_SHOPIFY_PREDICTIVE_SEARCH_TIMEOUT_SECONDS = 12.0


async def _shopify_predictive_search_fallback(
    domain: str, model_number: str
) -> dict[str, Any] | None:
    """
    Shopify's public Predictive Search API -- no key, no auth, same endpoint
    the theme's own search-as-you-type box calls client-side.

    The fix here is a single documented query parameter:
    `resources[options][unavailable_products]=show` -- Shopify's own
    official flag to include sold-out products in predictive search results,
    which are EXCLUDED by default. Without it this endpoint has exactly the
    same blind spot as the theme's visible search box; with it, an
    out-of-stock product's page is returned like any other.

    Returns a scraped_data-shaped dict built from the API's own title/body
    fields (no second fetch needed), or None on any failure: not a Shopify
    site, endpoint disabled, no matching product, network error. Never
    raises.
    """
    url = (
        f"https://{domain}/search/suggest.json"
        f"?q={quote_plus(model_number)}"
        f"&resources[type]=product"
        f"&resources[limit]=10"
        f"&resources[options][unavailable_products]=show"
    )
    try:
        async with httpx.AsyncClient(timeout=_SHOPIFY_PREDICTIVE_SEARCH_TIMEOUT_SECONDS) as client:
            response = await client.get(url)
        if response.status_code != 200:
            return None
        products = (response.json().get("resources", {}).get("results", {}) or {}).get("products") or []
        if not isinstance(products, list):
            return None
    except Exception as e:
        logger.debug(f"Shopify predictive search not usable on {domain}: {e}")
        return None

    needle = _normalise_for_match(model_number)
    if not needle:
        return None

    for product in products:
        title = str(product.get("title") or "")
        handle = str(product.get("handle") or "")
        path = str(product.get("url") or "")
        identity = _normalise_for_match(title) + _normalise_for_match(handle) + _normalise_for_match(path)
        if needle not in identity:
            continue

        content = _clean_html_to_text(f"{title}\n{product.get('body', '')}")
        if not content.strip():
            continue

        product_url = path if path.startswith("http") else f"https://{domain}{path}"
        stock_note = "in stock" if product.get("available") else "OUT OF STOCK"
        logger.info(
            f"Found {model_number} on {domain} via Shopify predictive search "
            f"({stock_note}, unavailable_products=show) after the site's own "
            f"search excluded it."
        )
        return {
            "url": product_url,
            "source_type": "official",
            "content": content,
            "candidate_titles": [title] if title else [],
        }

    return None


async def _official_out_of_stock_fallback(
    domain: str, model_number: str, brand_name: str, require_brand_identity: bool
) -> dict[str, Any] | None:
    """
    Owner-reported: a product genuinely on the brand's OFFICIAL site was not
    being found. Root cause: many storefront platforms (Shopify, WooCommerce,
    Magento defaults) exclude out-of-stock items from their OWN on-site
    search results -- so a real, live product page returns nothing from
    every search URL pattern tried, and the existing bail-out logic above
    reads "search works (brand appears), model doesn't" as proof the domain
    does not stock it. For an out-of-stock item that inference is wrong: the
    page exists, it just isn't in the search index.

    Three fallbacks, tried in order, official domains ONLY (2026-08-09,
    owner-directed -- explicitly scoped to the brand's own site, not
    retailers; owner-requested to be "universal" across platforms rather
    than WooCommerce-only, and to avoid depending on a Google key the owner
    does not currently have):

      1. WooCommerce's public Store API (_woocommerce_store_api_fallback) --
         no key needed, directly queries the product data the "hide out of
         stock" setting only hides from the THEME, not the data itself.
      2. Shopify's public Predictive Search API
         (_shopify_predictive_search_fallback) -- also no key needed. The
         fix there is a single documented Shopify query parameter,
         `resources[options][unavailable_products]=show`, which forces
         sold-out products BACK INTO results that exclude them by default.
      3. A `site:{domain}`-restricted Google search, IF configured (bonus
         for any OTHER platform, e.g. Magento, custom-built; zero cost when
         no key is set, which is the owner's current setup).

    Cheap-to-expensive, no-key-first ordering: 1 and 2 are each a single
    JSON request with no external dependency and no daily quota, so they're
    tried before touching the optional, quota-limited Google tier. Every
    candidate this finds still goes through the SAME identity checks as any
    other source (model_matches_identity, brand_matches_identity for a
    shared host) -- this only widens WHERE a URL/product can be found, never
    what counts as proof once it's fetched.

    Returns a scraped_data-shaped dict on success, or None (never raises) --
    callers fall through to the existing bail-out/settle behaviour exactly
    as before when nothing here can help.
    """
    def _identity_ok(candidate: dict[str, Any]) -> bool:
        return not require_brand_identity or brand_matches_identity(
            brand_name, candidate["url"], candidate["candidate_titles"]
        )

    # Sequential, not gathered: each is a short-circuit -- once one platform
    # fallback finds the product, there's no reason to also query the other.
    woo = await _woocommerce_store_api_fallback(domain, model_number)
    if woo and _identity_ok(woo):
        return woo

    shopify = await _shopify_predictive_search_fallback(domain, model_number)
    if shopify and _identity_ok(shopify):
        return shopify

    if not google_search_client.configured:
        return None

    query = f"site:{domain} {brand_name} {model_number}".strip()
    try:
        urls = await google_search_client.search(query)
    except Exception as e:
        logger.warning(f"Official-site out-of-stock fallback search failed for {domain}: {e}")
        return None

    for url in urls[:3]:
        try:
            result = await smart_fetch(url, model_number, allow_tier2=True)
        except Exception as e:
            logger.warning(f"Could not fetch out-of-stock fallback candidate {url}: {e}")
            continue
        if not (result.success and result.content
                and search_result_mentions_product(result.content, model_number)):
            continue
        if not model_matches_identity(model_number, result.url or url, result.candidate_titles):
            continue
        if require_brand_identity and not brand_matches_identity(
            brand_name, result.url or url, result.candidate_titles
        ):
            continue

        logger.info(
            f"Found {brand_name} {model_number} on {domain} via Google site-search "
            f"after the site's own search excluded it (likely out of stock): {url}"
        )
        return {
            "url": result.url or url,
            "source_type": "official",
            "content": result.content,
            "candidate_titles": list(result.candidate_titles),
        }

    return None


async def scrape_product(
    brand_name: str, model_number: str, tiers_to_run: tuple | None = None
) -> dict[str, Any]:
    """
    Discovers and scrapes sources for one product.

    Source discovery returns SEVERAL candidate search URLs per domain because
    storefront platforms differ (Shopify, WooCommerce, Magento, custom) and the
    right one is not known in advance. This walks them per domain and stops at
    the first whose content actually names the model number -- proof the search
    worked, rather than an assumption about the platform. The winning pattern is
    cached so later products on that site cost a single request.

    A page that loads but does not mention the product is discarded, not passed
    on: feeding a "no results" page to the Extractor invites it to describe
    whatever unrelated products the page happened to list.
    """
    sources = await resolve_sources(brand_name, model_number, tiers_to_run=tiers_to_run)

    if not sources:
        return {
            "failure": FailureInfo(
                category="no_reliable_source_found",
                detail=(
                    f"No official brand domain or trusted secondary source is configured "
                    f"for {brand_name} {model_number}. Add one in the Taxonomy Manager "
                    f"or Settings -> Trusted Secondary Sources."
                ),
            )
        }

    # Preserve trust order while grouping the candidate URLs of each domain.
    by_domain: dict[str, list[dict[str, str]]] = {}
    for source in sources:
        by_domain.setdefault(source.get("domain") or source["url"], []).append(source)

    scraped_data: list[dict[str, str]] = []
    # Tracks whether any source served an anti-bot / CAPTCHA challenge rather than
    # a real page. If nothing usable is scraped AND a block was seen, the operator
    # is told to paste Details -- the actionable truth -- instead of the misleading
    # "product not listed".
    blocked = False

    # Domains that need no second look: they either produced a source, or a
    # RENDERED page proved they do not stock the product.
    #
    # A pass-1 verdict is deliberately NOT enough to land here. Pass 1 is curl
    # only, so on a JS storefront it sees an unrendered shell -- and every
    # storefront's nav lists brand names, so "the brand appears but the model
    # does not" looks like proof when it is nothing of the kind. Treating that as
    # final excludes precisely the JS sites pass 2 exists to handle: measured on
    # 4 such domains, pass 2 made ZERO fetches and the product failed as
    # `source_unreachable` even though the browser would have found it on all 4.
    settled_domains: set[str] = set()

    for pass_num, allow_tier2 in ((1, False), (2, True)):
        attempted = 0          # per-pass budget; see MAX_TIER1/TIER2_ATTEMPTS
        consecutive_empty_domains = 0
        max_attempts = MAX_TIER2_ATTEMPTS if allow_tier2 else MAX_TIER1_ATTEMPTS

        if pass_num == 2:
            # The cheap pass already answered the question -- do not pay for a
            # browser to confirm what is settled.
            if _corroboration_satisfied(scraped_data):
                break
            pending = [d for d in by_domain if d not in settled_domains]
            if not pending:
                break
            logger.info(
                f"Pass 1 (no browser) left {brand_name} {model_number} with "
                f"{len(scraped_data)} source(s); starting pass 2 with Playwright "
                f"allowed across {len(pending)} remaining domain(s)."
            )

        for domain, candidates in by_domain.items():
            if domain in settled_domains:
                continue
            # THE MAIN STOP. An official source plus one cross-check already confirms
            # everything that is ever going to be confirmed, so the rest of the list
            # cannot change a single output -- it can only cost time. On the measured
            # run this fires at ~9s instead of running to the attempt ceiling at 137s.
            if _corroboration_satisfied(scraped_data):
                logger.info(
                    f"Corroboration satisfied for {brand_name} {model_number} with "
                    f"{len(scraped_data)} source(s) including an official one after "
                    f"{attempted} attempt(s); further sources cannot change the result."
                )
                break

            # Diminishing returns. Covers the case the rule above cannot: a product
            # with no official source available, where the old code would still walk
            # the entire configured list one dead domain at a time.
            if consecutive_empty_domains >= MAX_CONSECUTIVE_EMPTY_DOMAINS:
                logger.info(
                    f"{consecutive_empty_domains} consecutive domains yielded nothing for "
                    f"{brand_name} {model_number}; stopping with {len(scraped_data)} source(s) "
                    f"rather than walking the remaining {len(by_domain) - attempted} domain(s)."
                )
                break

            # Stop once enough independent sources are in hand. With 20+ configured
            # retailers, scraping every one would take many minutes per product;
            # corroboration only needs a handful of agreeing sources, and domains are
            # tried in trust order (official, then trusted, then web), so the first
            # few are the most authoritative.
            if len(scraped_data) >= MAX_SOURCES_FOR_CORROBORATION:
                logger.info(
                    f"Collected {len(scraped_data)} sources for {brand_name} {model_number}; "
                    f"stopping early (cap {MAX_SOURCES_FOR_CORROBORATION})."
                )
                break
            if attempted >= max_attempts:
                logger.info(
                    f"Pass {pass_num} hit its {max_attempts}-attempt ceiling for {brand_name} "
                    f"{model_number} with {len(scraped_data)} source(s); ending this pass."
                )
                break
            sources_before_domain = len(scraped_data)
            for source in candidates:
                attempted += 1
                try:
                    result = await smart_fetch(
                        source["url"], model_number, allow_tier2=allow_tier2
                    )
                except Exception as e:
                    logger.warning(f"Scrape failed for {source['url']}: {e}")
                    continue

                if not result.success or not result.content:
                    continue

                # An anti-bot challenge loads with content but is not the product. Flag
                # it as a block (not a no-match) so the escalation is actionable.
                if is_block_page(result.content):
                    blocked = True
                    logger.warning(
                        f"{source['url']} returned an anti-bot/block page (Cloudflare etc.); "
                        f"skipping. Operator can paste Details to bypass."
                    )
                    continue

                if not search_result_mentions_product(result.content, model_number):
                    # Domain bail-out: if the search page loaded successfully AND
                    # mentions the brand name (proof the search engine is working on
                    # this domain, not just returning an error/empty page), but does
                    # NOT mention our model number, this domain has confirmed it does
                    # not stock this product. Skip all remaining URL patterns for it.
                    #
                    # WHY THIS IS SAFE: we only bail when the brand appears in content,
                    # ruling out the case where a pattern returned the wrong platform's
                    # "no results" page (which would not mention the brand at all).
                    # This preserves the original multi-pattern logic for all cases
                    # where the search page is genuinely empty or wrong-platform.
                    # Use only the FIRST alphanumeric token of the brand name for
                    # the content check. Splitting on any separator (space, hyphen,
                    # underscore) handles all real-world brand name formats:
                    #   "WestPoint Pakistan" -> "WestPoint"
                    #   "WestPoint-Pakistan" -> "WestPoint"
                    #   "Kenwood"            -> "Kenwood"
                    brand_token = re.split(r"[^a-zA-Z0-9]", brand_name)[0] if brand_name else brand_name
                    if search_result_mentions_product(result.content, brand_token):
                        logger.info(
                            f"Domain {domain} (pass {pass_num}): search works (mentions "
                            f"'{brand_name}') but '{model_number}' is not stocked there. "
                            f"Skipping {len(candidates) - candidates.index(source) - 1} "
                            f"remaining URL pattern(s) for this domain."
                        )
                        # 2026-08-09 (owner-directed, official domains only): before
                        # accepting "search says not stocked" as final, try the
                        # out-of-stock fallback -- see _official_out_of_stock_fallback's
                        # docstring for why the site's OWN search is not reliable proof
                        # of absence for an out-of-stock item. Only worth the extra
                        # Google call once a browser has actually rendered the page
                        # (allow_tier2), same "final ONLY when rendered" rule as below.
                        if allow_tier2 and source["source_type"] == "official":
                            fallback = await _official_out_of_stock_fallback(
                                domain, model_number, brand_name,
                                require_brand_identity=bool(source.get("scope_path")),
                            )
                            if fallback:
                                scraped_data.append(fallback)
                                matched = template_of_url(domain, source["url"], brand_name, model_number)
                                if matched:
                                    await remember_working_template(domain, matched)
                                settled_domains.add(domain)
                                break
                        # Final ONLY when a browser rendered the page. In pass 1 the
                        # brand can appear in an unrendered shell's nav menu while the
                        # catalogue never loaded, so this is not yet proof of anything
                        # -- settling here is what silently excluded JS sites from
                        # pass 2 entirely.
                        if allow_tier2:
                            settled_domains.add(domain)
                        break  # skip remaining candidates for this domain, this pass
                    logger.debug(
                        f"{source['url']} loaded but does not mention {model_number}; "
                        f"treating as no-match"
                    )
                    continue

                # A Google/web result IS already a product detail page, not a search
                # listing, so it is used directly once it names the model -- there is
                # no further page to follow to. For a `web` (unvetted) source, brand
                # identity is still required so a wrong-product page cannot slip in.
                if source.get("is_direct") == "true":
                    # A direct product page must identify as this exact model (title/
                    # slug), guarding the IPRA/IPGA suffix trap on web results too.
                    if not model_matches_identity(model_number, result.url or source["url"],
                                                  result.candidate_titles):
                        logger.info(
                            f"Rejected direct result {source['url']}: title/URL is a different "
                            f"model variant than {model_number}."
                        )
                        continue
                    if (source["source_type"] == "web"
                            and not brand_matches_identity(brand_name, result.url or source["url"],
                                                           result.candidate_titles)):
                        logger.info(
                            f"Rejected direct web result {source['url']}: names {model_number} "
                            f"but does not identify as '{brand_name}'."
                        )
                        continue
                    detail = result
                else:
                    # A search hit is only a lead. The detail page is the evidence --
                    # see _follow_to_detail_page for why a listing alone is rejected.
                    detail = await _follow_to_detail_page(
                        result,
                        model_number,
                        brand_name=brand_name,
                        # A path scope is recorded only for hosts that serve more than
                        # one brand, so its presence is exactly the condition under
                        # which brand identity has to be proven.
                        require_brand_identity=bool(source.get("scope_path")),
                        allow_tier2=allow_tier2,
                    )
                if detail is None:
                    logger.info(
                        f"{source['url']} matched the query but no product page for "
                        f"{model_number} was found on {domain}; discarding this source"
                    )
                    brand_token = re.split(r"[^a-zA-Z0-9]", brand_name)[0] if brand_name else brand_name
                    if result.content and search_result_mentions_product(result.content, brand_token):
                        logger.info(
                            f"Search page on {domain} confirmed working (mentions '{brand_token}') "
                            f"but '{model_number}' detail page not found. Bailing out of remaining candidate patterns."
                        )
                        # Same out-of-stock fallback as the other bail-out above --
                        # see _official_out_of_stock_fallback's docstring.
                        if allow_tier2 and source["source_type"] == "official":
                            fallback = await _official_out_of_stock_fallback(
                                domain, model_number, brand_name,
                                require_brand_identity=bool(source.get("scope_path")),
                            )
                            if fallback:
                                scraped_data.append(fallback)
                                matched = template_of_url(domain, source["url"], brand_name, model_number)
                                if matched:
                                    await remember_working_template(domain, matched)
                                settled_domains.add(domain)
                                break
                        # Same rule as the bail-out above: only a rendered page
                        # settles a domain. Without this guard, a pass-1 shell that
                        # merely lists brand names in its nav retires the domain
                        # before the browser ever sees it.
                        if allow_tier2:
                            settled_domains.add(domain)
                        break
                    continue

                # Titles from BOTH pages: the listing shows how this seller names
                # the model alongside competitors, the detail page gives its full
                # title. More independent titles means better corroboration.
                scraped_data.append({
                    "url": detail.url,
                    "source_type": source["source_type"],
                    "content": detail.content,
                    "candidate_titles": list(dict.fromkeys(
                        result.candidate_titles + detail.candidate_titles
                    )),
                })

                matched_template = template_of_url(domain, source["url"], brand_name, model_number)
                if matched_template:
                    await remember_working_template(domain, matched_template)

                # This domain delivered -- never revisit it in pass 2.
                settled_domains.add(domain)
                break  # this domain answered; move to the next one

            # Feeds the diminishing-returns stop above. Counted per DOMAIN, not per
            # URL pattern: one domain legitimately costs several attempts while its
            # platform is identified, and counting those as separate misses would
            # abandon the list far too early.
            if len(scraped_data) > sources_before_domain:
                consecutive_empty_domains = 0
            else:
                consecutive_empty_domains += 1

    if not scraped_data:
        if blocked:
            return {
                "failure": FailureInfo(
                    category="source_blocked",
                    detail=(
                        f"Automated access to the source(s) for {brand_name} {model_number} was "
                        f"blocked by anti-bot protection (Cloudflare etc.). Paste this product's "
                        f"Details (and optionally its Website Link) to add it without scraping."
                    ),
                )
            }
        return {
            "failure": FailureInfo(
                category="source_unreachable",
                detail=(
                    f"Tried {attempted} search URL(s) across {len(by_domain)} source(s) for "
                    f"{brand_name} {model_number}; none returned a page mentioning the model "
                    f"number. The product may not be listed on the configured sources, or the "
                    f"sites were unreachable."
                ),
            )
        }

    return {"scraped_data": scraped_data}
