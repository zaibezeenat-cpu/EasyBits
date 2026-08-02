import logging
import re
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from app.models.failure import FailureInfo
from app.scraping.fetcher import smart_fetch
from app.scraping.playwright_client import is_block_page
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
MAX_SOURCES_FOR_CORROBORATION = 5

# Hard ceiling on scrape attempts per product, so a large source list cannot
# blow up processing time. A brand's own site alone can burn ~12 attempts trying
# every URL pattern when the product simply is not listed there; this bounds the
# worst case so one product cannot stall a whole batch.
MAX_SCRAPE_ATTEMPTS = 25


async def _follow_to_detail_page(search_result, model_number: str,
                                 brand_name: str = "", require_brand_identity: bool = False):
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
            detail = await smart_fetch(link, model_number)
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


async def scrape_product(
    brand_name: str, model_number: str, tiers_to_run: Optional[tuple] = None
) -> Dict[str, Any]:
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
    by_domain: Dict[str, List[Dict[str, str]]] = {}
    for source in sources:
        by_domain.setdefault(source.get("domain") or source["url"], []).append(source)

    scraped_data: List[Dict[str, str]] = []
    attempted = 0
    # Tracks whether any source served an anti-bot / CAPTCHA challenge rather than
    # a real page. If nothing usable is scraped AND a block was seen, the operator
    # is told to paste Details -- the actionable truth -- instead of the misleading
    # "product not listed".
    blocked = False

    for domain, candidates in by_domain.items():
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
        if attempted >= MAX_SCRAPE_ATTEMPTS:
            logger.info(
                f"Reached the {MAX_SCRAPE_ATTEMPTS}-attempt ceiling for {brand_name} "
                f"{model_number} with {len(scraped_data)} source(s); stopping to bound time."
            )
            break
        for source in candidates:
            attempted += 1
            try:
                result = await smart_fetch(source["url"], model_number)
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
                        f"Domain {domain} confirmed: search works (mentions '{brand_name}') "
                        f"but '{model_number}' is not stocked there. "
                        f"Skipping {len(candidates) - candidates.index(source) - 1} "
                        f"remaining URL pattern(s) for this domain."
                    )
                    break  # skip remaining candidates for this domain
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
            break  # this domain answered; move to the next one

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
