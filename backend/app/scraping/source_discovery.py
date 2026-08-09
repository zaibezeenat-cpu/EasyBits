"""
Source discovery: decides WHICH URLs to scrape for a given product.

Tiered by trustworthiness, stopping at the first tier that yields sources:

  1. Search engine (Firecrawl)  -- only when FIRECRAWL_API_KEY is set.
  2. Official brand domain      -- from the `brand_domain_aliases` table.
  3. Trusted secondary sources  -- from the `trusted_secondary_sources` table.
  4. Nothing found              -- escalate as no_reliable_source_found.

WHY THERE IS NO FREE SEARCH-ENGINE TIER (measured 2026-07-21, not assumed):
every free option was tested and none is usable for unattended automation.
    DuckDuckGo HTML   blocked (anti-bot interstitial)
    DuckDuckGo Lite   blocked
    Startpage         blocked
    Mojeek            CAPTCHA
    Bing              parses, but geo-locked to the wrong country (returned
                      Hungarian results for a Pakistani product, and ignored
                      setmkt=en-PK) AND rate-limited to ~2 queries
Scraping a search engine was therefore dropped rather than shipped as a feature
that silently fails. For this catalogue the domain tiers are also *better*: every
source is an authoritative brand or retailer site rather than an arbitrary
search result, which is exactly what the no-hallucination contract needs.
"""
import asyncio
import logging
import re
from typing import NamedTuple
from urllib.parse import quote_plus, urlparse

from app.db.repositories.sources import sources_repo
from app.scraping.firecrawl_client import FirecrawlClient
from app.scraping.google_search_client import google_search_client

logger = logging.getLogger(__name__)
firecrawl_client = FirecrawlClient()


def _normalise_domain(url_or_domain: str) -> str:
    """Bare lowercase host, no scheme and no leading www."""
    value = (url_or_domain or "").strip().lower()
    if "//" in value:
        value = urlparse(value).netloc
    value = value.removeprefix("www.")
    return value


class SourceScope(NamedTuple):
    """
    A configured source: a host plus an OPTIONAL path that narrows it to one
    brand's section of that host.

    WHY THE PATH CANNOT BE DISCARDED (measured on the real sites, 2026-07-21):
    one host can be the official source for several brands. DWP Home distributes
    both EcoStar and Gree, and their official presences are `dwphome.pk/ecostar`
    and `dwphome.pk/gree`. Haier's official Pakistan site is `haier.com/pk/`,
    a subdirectory of the global site whose model lineup and warranty differ.
    Reducing these to a bare host makes two different brands indistinguishable
    and silently swaps a regional site for a global one.
    """
    host: str
    path: str  # "" or a leading-slash prefix such as "/ecostar"

    @property
    def key(self) -> str:
        """Stable identifier used for grouping, de-duplication and template caching."""
        return f"{self.host}{self.path}"

    @property
    def base_url(self) -> str:
        return f"https://{self.host}{self.path}"


def parse_source_scope(url_or_domain: str) -> SourceScope:
    """
    Splits operator input into host + path scope.

        "https://dwphome.pk/ecostar"  -> SourceScope("dwphome.pk", "/ecostar")
        "https://www.haier.com/pk/"   -> SourceScope("haier.com", "/pk")
        "kenwoodpakistan.pk"          -> SourceScope("kenwoodpakistan.pk", "")

    A trailing slash is stripped so "/pk/" and "/pk" produce one scope rather
    than two that cache and de-duplicate separately.
    """
    value = (url_or_domain or "").strip().lower()
    if not value:
        return SourceScope("", "")

    if "//" in value:
        parsed = urlparse(value)
        host, path = parsed.netloc, parsed.path
    else:
        host, _, rest = value.partition("/")
        path = f"/{rest}" if rest else ""

    host = host.removeprefix("www.")

    path = path.rstrip("/")
    if path and not path.startswith("/"):
        path = f"/{path}"

    return SourceScope(host, path)


def _identity_tokens(text: str) -> set[str]:
    """Alphanumeric tokens of a URL slug or page title, lowercased."""
    return {t for t in re.split(r"[^a-z0-9]+", (text or "").lower()) if t}


def model_matches_identity(model_number: str, url: str, titles: list[str]) -> bool:
    """
    True when a detail page IS about this exact model, judged by its identity
    (URL slug + title), not merely the body.

    WHY THE BODY IS NOT ENOUGH (the IPRA/IPGA trap): "HRF-316 IPRA" (Red) and
    "HRF-316 IPGA" (Green) differ by one character. A retailer's IPRA page often
    cross-links the IPGA variant in a "related products" strip, so the IPGA code
    appears in the IPRA page's BODY -- and a body-only match would accept the
    wrong-colour page and blend the two products' specs. The page's own title
    and URL slug name the product it is actually about, so the exact model code
    must appear THERE. Punctuation-insensitive, so "HRF-316 IPGA" matches
    "hrf-316-ipga" and "316IPGA".
    """
    def flat(text: str) -> str:
        return re.sub(r"[^a-z0-9]", "", (text or "").lower())

    needle = flat(model_number)
    if not needle:
        return False
    identity = flat(urlparse(url or "").path) + "".join(flat(t) for t in (titles or []))

    # Best case: the full model code appears verbatim in the identity (real
    # retailer URLs usually include it, e.g. ".../haier-hrf-246-ipga-green").
    if needle in identity:
        return True

    # Fallback for titles that drop a generic prefix like "HRF" ("316 IPGA"):
    # require the DISTINCTIVE parts -- every token containing a digit, plus the
    # trailing letter suffix that separates siblings (IPGA vs IPRA). This still
    # rejects the wrong variant (its suffix is absent) without over-rejecting a
    # page that merely omits the family prefix.
    tokens = [t for t in re.split(r"[^a-z0-9]+", model_number.lower()) if t]
    distinctive = [t for t in tokens if any(c.isdigit() for c in t)]
    if tokens and not any(c.isdigit() for c in tokens[-1]):
        distinctive.append(tokens[-1])
    return bool(distinctive) and all(t in identity for t in distinctive)


def brand_matches_identity(brand_name: str, url: str, titles: list[str]) -> bool:
    """
    True when a product page identifies itself as belonging to `brand_name`.

    Checks ONLY the page's identity fields -- its URL slug and its titles --
    never the body. THIS DISTINCTION IS THE WHOLE POINT, and it was measured
    rather than assumed. On dwphome.pk, which sells both brands, the body of a
    single EcoStar product page mentions "ecostar" 75 times and "gree" 47 times
    (site-wide navigation links every brand). A body-text check therefore passes
    for BOTH brands and proves nothing. The title and h1 are unambiguous on the
    same pages:
        EcoStar product -> "EcoStar Ario MAX Series 1 TON Split AC"
        Gree product    -> "GREE Airy Pro 1 TON Split AC (Inverter) - GS-12AITH24S-T3"

    Token matching, not substring: "gree" is a substring of "degree" and
    "agree", so a substring test would match unrelated marketing copy.
    """
    brand_tokens = _identity_tokens(brand_name)
    if not brand_tokens:
        return False

    candidates = _identity_tokens(urlparse(url or "").path)
    for title in titles or []:
        candidates |= _identity_tokens(title)

    return brand_tokens.issubset(candidates)


# Site search is platform-agnostic by trial, not by configuration. Every
# storefront exposes search differently (Shopify, WooCommerce, Magento, custom),
# and requiring someone to know and record each platform does not scale to new
# retailers. Instead every candidate pattern is tried and the result is VALIDATED
# by checking that the product's model number actually appears in the page --
# which is direct proof the search worked, rather than an assumption about the
# platform. The winning pattern is then cached per domain so later products on
# the same site go straight to the URL that works.
#
# Ordering is by observed hit rate, cheapest-to-succeed first. Measured:
#   surmawala.pk        /search?q=   -> FOUND the model number
#   japanelectronics.pk /?s=         -> ignored the query (identical output twice)
CANDIDATE_SEARCH_PATTERNS: tuple[str, ...] = (
    "https://{domain}/search?q={query}",                    # Shopify + many custom
    "https://{domain}/?s={query}&post_type=product",        # WooCommerce
    "https://{domain}/?s={query}",                          # WordPress generic
    "https://{domain}/search/?q={query}",                   # common variant
    "https://{domain}/catalogsearch/result/?q={query}",     # Magento
)

# Cache of {domain: template_that_worked}, persisted in app_settings so it
# survives restarts and is visible/editable from the frontend.
SEARCH_TEMPLATE_SETTING_KEY = "source_search_url_templates"


def build_site_search_url(
    domain: str,
    brand_name: str,
    model_number: str,
    template: str | None = None,
) -> str:
    """
    Builds an on-site search URL.

    Searching by "<brand> <model>" gives the best hit rate -- store search
    engines rarely match a full marketing title.

    `domain` may carry a path scope ("dwphome.pk/ecostar"); it is substituted
    verbatim, which is what produces a section-scoped search URL.
    """
    query = quote_plus(f"{brand_name} {model_number}".strip())
    return (template or CANDIDATE_SEARCH_PATTERNS[0]).format(domain=domain, query=query)


def build_search_url_candidates(scope: "SourceScope | str", brand_name: str, model_number: str,
                                known_template: str | None = None) -> list[str]:
    """
    All URLs worth trying for one scope, best-known first.

    ORDER, AND WHY A SCOPED SOURCE STILL FALLS BACK TO THE ROOT:
      1. the scope's landing page ("https://dwphome.pk/ecostar")
      2. search URLs under the scope path
      3. search URLs at the host root

    The landing page comes first because on a shared host it is the one page
    guaranteed to list only that brand's products -- verified live, where
    /ecostar links 145 distinct products and /gree links 113, with no overlap
    in their slugs.

    The root fallback exists because a brand section usually does NOT have its
    own search endpoint: on dwphome.pk the products under /ecostar are served
    from /product/..., so the section path is a landing page, not a URL prefix
    the whole catalogue sits beneath. Dropping the root fallback would leave
    scoped brands with no working search at all. Cross-brand contamination is
    prevented downstream by `brand_matches_identity`, not by the URL shape.

    A previously-successful template is tried first so a working site costs a
    single request.
    """
    if isinstance(scope, str):
        scope = parse_source_scope(scope)

    templates = list(CANDIDATE_SEARCH_PATTERNS)
    if known_template and known_template in templates:
        templates.remove(known_template)
    if known_template:
        templates.insert(0, known_template)

    urls: list[str] = []
    if scope.path:
        urls.append(scope.base_url)
        urls.extend(build_site_search_url(scope.key, brand_name, model_number, t) for t in templates)
    urls.extend(build_site_search_url(scope.host, brand_name, model_number, t) for t in templates)

    # Preserve order while dropping repeats (an unscoped source would otherwise
    # generate each search URL twice).
    return list(dict.fromkeys(urls))


def search_result_mentions_product(content: str, model_number: str) -> bool:
    """
    True when scraped content actually mentions the model number.

    This is the validation that makes platform detection unnecessary: a search
    page that does not name the product did not find it, whatever the platform
    or HTTP status. Punctuation is ignored so "KLU-12B03S" still matches
    "KLU 12B03S" or "klu12b03s".
    """
    if not content or not model_number:
        return False

    def normalise(value: str) -> str:
        return re.sub(r"[^a-z0-9]", "", value.lower())

    return normalise(model_number) in normalise(content)


async def get_cached_search_templates() -> dict[str, str]:
    """Per-domain templates previously proven to work; {} when none yet."""
    try:
        from app.db.repositories.settings import settings_repo
        value = await settings_repo.get_setting(SEARCH_TEMPLATE_SETTING_KEY)
        return value if isinstance(value, dict) else {}
    except Exception as e:
        logger.warning(f"Could not read cached search templates: {e}")
        return {}


# Guards the read-modify-write below. Without it, two products discovering
# sources concurrently (BATCH_CONCURRENCY > 1) can both read the same starting
# dict, and whichever writes last silently drops the other's learned template
# -- a lost update, not a crash, so it would never surface as an error.
_template_cache_lock = asyncio.Lock()


async def remember_working_template(domain: str, template: str) -> None:
    """Records the pattern that worked for a domain so it is tried first next time."""
    try:
        from app.db.repositories.settings import settings_repo
        async with _template_cache_lock:
            current = await get_cached_search_templates()
            if current.get(domain) == template:
                return
            current[domain] = template
            await settings_repo.update_setting(SEARCH_TEMPLATE_SETTING_KEY, current)
        logger.info(f"Learned search pattern for {domain}: {template}")
    except Exception as e:
        # Caching is an optimisation; failing to persist must not break discovery.
        logger.warning(f"Could not cache search template for {domain}: {e}")


def template_of_url(domain: str, url: str, brand_name: str, model_number: str) -> str | None:
    """
    Reverse-maps a URL back to the pattern that produced it, for caching.

    Tries both the scoped form ("dwphome.pk/ecostar") and the bare host, since
    a scoped source generates candidates at both levels and either may be the
    one that worked. Returns None for the landing-page candidate, which is not
    a template and must not be cached as one.
    """
    scope = parse_source_scope(domain)
    for prefix in dict.fromkeys((scope.key, scope.host)):
        if not prefix:
            continue
        for template in CANDIDATE_SEARCH_PATTERNS:
            if build_site_search_url(prefix, brand_name, model_number, template) == url:
                return template
    return None


async def _tier_search_engine(brand_name: str, model_number: str) -> list[dict[str, str]]:
    """Tier 1 — only active when a Firecrawl key is configured."""
    if not firecrawl_client.app:
        return []

    results = await firecrawl_client.search(f"{brand_name} {model_number} official specifications")
    if not results:
        return []

    normalised_brand = re.sub(r"[^a-z0-9]", "", brand_name.lower())
    aliases = {_normalise_domain(a) for a in await sources_repo.get_brand_aliases(brand_name)}

    sources: list[dict[str, str]] = []
    for result in results:
        url = result.get("url")
        if not url:
            continue
        domain = _normalise_domain(url)
        if normalised_brand and normalised_brand in domain.replace("-", "").replace(".", "") or domain in aliases:
            sources.append({"url": url, "source_type": "official"})
    return sources


async def _tier_official_domain(brand_name: str, model_number: str) -> list[dict[str, str]]:
    """
    Tier 2 — the brand's own site, from `brand_domain_aliases`.

    Empty by default and deliberately NOT auto-populated: probing likely domain
    patterns produced confident-looking but wrong matches (royal.com.pk is a
    school, gaba.pk is a rug store, elite.com.pk is a printing firm). Scraping
    those for appliance specs would fabricate data with full confidence, so
    these must be confirmed by a human via the Taxonomy Manager.
    """
    domains = await sources_repo.get_brand_aliases(brand_name)
    cached = await get_cached_search_templates()
    sources: list[dict[str, str]] = []
    for raw_domain in domains:
        if not raw_domain:
            continue
        scope = parse_source_scope(raw_domain)
        if not scope.host:
            continue
        for url in build_search_url_candidates(scope, brand_name, model_number, cached.get(scope.key)):
            sources.append({
                "url": url,
                "source_type": "official",
                "domain": scope.key,
                # Set only for shared hosts. Its presence is what tells the
                # orchestrator to demand brand identity on the detail page,
                # because this host also serves other brands.
                "scope_path": scope.path,
            })
    return sources


async def _tier_trusted_secondary(brand_name: str, model_number: str) -> list[dict[str, str]]:
    """Tier 3 — retailer sites the owner has approved (Japan Electronics, Surmawala, ...)."""
    configured = await sources_repo.get_active_trusted_secondary_sources()
    cached = await get_cached_search_templates()
    sources: list[dict[str, str]] = []
    for entry in configured:
        if not entry.get("domain"):
            continue
        scope = parse_source_scope(entry["domain"])
        if not scope.host:
            continue
        for url in build_search_url_candidates(scope, brand_name, model_number, cached.get(scope.key)):
            sources.append({
                "url": url,
                "source_type": "trusted_secondary",
                "domain": scope.key,
                "scope_path": scope.path,
            })
    return sources


GOOGLE_SEARCH_CACHE_KEY = "google_search_url_cache"
_GOOGLE_CACHE_MAX_ENTRIES = 500


async def _get_cached_google_urls(query: str) -> list[str] | None:
    """Cached Google result URLs for a query, or None if never searched.

    Prevents the 100/day free-tier quota being burned on retries and on
    re-processing the same model in a later batch.
    """
    try:
        from app.db.repositories.settings import settings_repo
        cache = await settings_repo.get_setting(GOOGLE_SEARCH_CACHE_KEY)
        if isinstance(cache, dict):
            hit = cache.get(query)
            if isinstance(hit, list):
                return hit
    except Exception as e:
        logger.warning(f"Could not read Google search cache: {e}")
    return None


# Same lost-update risk as _template_cache_lock above, on the cache that
# guards the Google CSE free-tier 100/day quota specifically -- a lost write
# here means the SAME query gets searched again later, burning quota the
# cache exists to save.
_google_cache_lock = asyncio.Lock()


async def _cache_google_urls(query: str, urls: list[str]) -> None:
    try:
        from app.db.repositories.settings import settings_repo
        async with _google_cache_lock:
            cache = await settings_repo.get_setting(GOOGLE_SEARCH_CACHE_KEY)
            cache = cache if isinstance(cache, dict) else {}
            # Bound the cache so one settings row cannot grow without limit.
            if len(cache) >= _GOOGLE_CACHE_MAX_ENTRIES and query not in cache:
                for stale_key in list(cache)[: len(cache) - _GOOGLE_CACHE_MAX_ENTRIES + 1]:
                    cache.pop(stale_key, None)
            cache[query] = urls
            await settings_repo.update_setting(GOOGLE_SEARCH_CACHE_KEY, cache)
    except Exception as e:
        logger.warning(f"Could not write Google search cache: {e}")


def classify_web_url(
    url: str, brand_alias_hosts: set[str], trusted_hosts: set[str], brand_name: str
) -> dict[str, str]:
    """
    Types a Google result URL by its domain so trust order is preserved:
    a brand-owned host -> official, a configured retailer -> trusted_secondary,
    anything else -> web (lowest trust).
    """
    domain = _normalise_domain(url)
    normalised_brand = re.sub(r"[^a-z0-9]", "", brand_name.lower())
    flat = domain.replace("-", "").replace(".", "")
    if domain in brand_alias_hosts or (normalised_brand and normalised_brand in flat):
        source_type = "official"
    elif domain in trusted_hosts:
        source_type = "trusted_secondary"
    else:
        source_type = "web"
    # Google returns product/detail URLs directly, not search-result pages, so
    # the orchestrator must use the page itself rather than trying to follow it
    # to a further detail page.
    return {"url": url, "source_type": source_type, "domain": domain, "is_direct": "true"}


async def _tier_google_search(brand_name: str, model_number: str) -> list[dict[str, str]]:
    """
    Broad web tier -- only active when a Google Programmable Search key is set.

    Types every result by domain; `web` (unvetted) results are dropped in strict
    source-mode and kept only under priority mode, reusing the existing toggle.
    """
    if not google_search_client.configured:
        return []

    query = f"{brand_name} {model_number}".strip()
    urls = await _get_cached_google_urls(query)
    if urls is None:
        urls = await google_search_client.search(query)
        await _cache_google_urls(query, urls)
    if not urls:
        return []

    brand_alias_hosts = {_normalise_domain(a) for a in await sources_repo.get_brand_aliases(brand_name)}
    trusted_hosts = {
        _normalise_domain(e["domain"])
        for e in await sources_repo.get_active_trusted_secondary_sources()
        if e.get("domain")
    }

    from app.db.repositories.settings import settings_repo
    mode = await settings_repo.get_setting("source_mode")
    strict = mode != "priority"  # default strict unless explicitly priority

    sources: list[dict[str, str]] = []
    for url in urls:
        typed = classify_web_url(url, brand_alias_hosts, trusted_hosts, brand_name)
        if strict and typed["source_type"] == "web":
            # Strict mode never introduces an unvetted site; Google may still
            # have surfaced an official/trusted URL, which is kept.
            continue
        sources.append(typed)
    return sources


FREE_TIERS = ("search_engine", "official_domain", "trusted_secondary")
GOOGLE_TIER = ("google_search",)


async def resolve_sources(
    brand_name: str, model_number: str, tiers_to_run: tuple | None = None
) -> list[dict[str, str]]:
    """
    Returns [{url, source_type}] ordered most-trusted first, or [] when no tier
    produced anything.

    An empty list means "we could not reach a trustworthy source", NOT "this
    product has no facts". The caller must escalate as no_reliable_source_found
    so an outage can never be mistaken for a product legitimately lacking data.
    """
    # Order IS the priority: brand official site, then the owner's selected
    # retailers, then broad Google web results last (typed and gated).
    #
    # `tiers_to_run` lets the caller run the FREE tiers first and hold the paid/
    # quota-limited Google tier back, invoking it only when corroboration is
    # still incomplete. That keeps most products entirely free.
    tiers = (
        ("search_engine", _tier_search_engine),
        ("official_domain", _tier_official_domain),
        ("trusted_secondary", _tier_trusted_secondary),
        ("google_search", _tier_google_search),
    )
    if tiers_to_run is not None:
        tiers = tuple(t for t in tiers if t[0] in tiers_to_run)

    collected: list[dict[str, str]] = []
    for tier_name, tier_fn in tiers:
        try:
            found = await tier_fn(brand_name, model_number)
        except Exception as e:
            # A tier failing (network, missing table row) must not abort
            # discovery -- fall through to the next, less-preferred tier.
            logger.warning(f"Source discovery tier '{tier_name}' failed for "
                           f"{brand_name} {model_number}: {e}")
            continue
        if found:
            logger.info(f"Source discovery tier '{tier_name}' returned "
                        f"{len(found)} source(s) for {brand_name} {model_number}")
            collected.extend(found)

    if not collected:
        logger.info(f"No sources found for {brand_name} {model_number} across all tiers")

    # De-duplicate while preserving trust order.
    seen: set[str] = set()
    unique: list[dict[str, str]] = []
    for source in collected:
        if source["url"] not in seen:
            seen.add(source["url"])
            unique.append(source)
    return unique
