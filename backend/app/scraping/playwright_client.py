import re

from bs4 import BeautifulSoup
from playwright.async_api import async_playwright
from app.scraping.models import ScrapeResult
from app.core.logging import logger

# BUG FIX (Phase 3 integration test, real LLM calls): raw page.content() is
# the full HTML document -- scripts, styles, nav/footer boilerplate, inline
# CSS -- often tens of thousands of tokens for a single product page. Sent
# directly into the Extractor prompt, this blew Gemini's free-tier
# tokens-per-minute quota on ONE request and made Groq reject the prompt
# outright as too long ("Please reduce the length of the messages"). Neither
# failure was a fluke; every real scrape would hit one or the other. A hard
# cap keeps a single unusually large page from repeating the same failure.
_MAX_CLEANED_CONTENT_CHARS = 15000

# Page-load budget in milliseconds. 30s was too short and failed EVERY real
# scrape: the target Pakistani retailer sites serve ~600KB pages from slow
# hosts, and a manual probe at 45s succeeded where 30s timed out. Raised with
# headroom, and retried once, because a timeout here is indistinguishable
# downstream from "this product has no data" -- the expensive failure mode.
_PAGE_TIMEOUT_MS = 60000
_LOAD_ATTEMPTS = 2


def extract_product_links(html: str, base_url: str, model_number: str) -> list[str]:
    """
    Finds likely product-detail links on a search-results page.

    A search listing tells us the product EXISTS but rarely carries its specs --
    the detail page does. Links are ranked by how strongly they identify the
    product: one whose href or anchor text contains the model number is almost
    certainly the right item, so those come first; generic /product/ links
    follow as a weaker fallback.
    """
    from urllib.parse import urldefrag, urljoin, urlparse

    def normalise(value: str) -> str:
        return re.sub(r"[^a-z0-9]", "", (value or "").lower())

    soup = BeautifulSoup(html, "html.parser")
    model_key = normalise(model_number)
    base_host = urlparse(base_url).netloc
    # Fragments are stripped before comparison so "…?q=X#MainContent" is
    # recognised as the SAME page. Without this, a "skip to content" anchor was
    # followed as if it were the product page -- it matched only because the
    # search URL itself contains the model number.
    current_page, _ = urldefrag(base_url)

    # Paths that are never a product detail page.
    NON_PRODUCT = ("/cart", "/checkout", "/account", "/login", "/search",
                   "/collections/all", "/pages/", "/blogs/", "/policies/")

    strong: list[str] = []
    weak: list[str] = []
    for a in soup.find_all("a", href=True):
        href, _ = urldefrag(urljoin(base_url, a["href"]))
        if not href or href == current_page:
            continue  # same-page anchor
        if urlparse(href).netloc != base_host:
            continue  # never wander off the trusted domain
        if any(href.lower().endswith(ext) for ext in (".jpg", ".png", ".webp", ".pdf")):
            continue
        path = urlparse(href).path.lower()
        if any(seg in path for seg in NON_PRODUCT):
            continue

        # Only the link's own text/href may vouch for it -- the query string is
        # excluded because it echoes the search terms on every link.
        haystack = normalise(path + " " + a.get_text(" ", strip=True))
        if model_key and model_key in haystack:
            if href not in strong:
                strong.append(href)
        elif any(seg in path for seg in ("/product/", "/products/", "/shop/", "/p/")):
            if href not in weak:
                weak.append(href)

    return strong + weak


def extract_candidate_titles(html: str, model_number: str) -> list[str]:
    """
    Collects how other sellers title this exact model.

    Sources, in descending reliability: the page's own <title> and <h1> (a
    detail page names one product), then product-link anchor text and common
    product-title classes on a listing page.

    Only titles that actually contain the model number are returned -- a title
    for a different product says nothing about this one, and mixing them in
    would let an unrelated product's features leak into our title.
    """
    def normalise(value: str) -> str:
        return re.sub(r"[^a-z0-9]", "", (value or "").lower())

    model_key = normalise(model_number)
    if not model_key:
        return []

    soup = BeautifulSoup(html, "html.parser")
    candidates: list[str] = []

    if soup.title and soup.title.string:
        candidates.append(soup.title.string)
    for tag in soup.find_all(["h1", "h2"]):
        candidates.append(tag.get_text(" ", strip=True))
    for a in soup.find_all("a", href=True):
        text = a.get_text(" ", strip=True)
        if text:
            candidates.append(text)
    for node in soup.select(".product-title, .woocommerce-loop-product__title, .product_title"):
        candidates.append(node.get_text(" ", strip=True))

    seen: set[str] = set()
    titles: list[str] = []
    for candidate in candidates:
        cleaned = re.sub(r"\s+", " ", candidate or "").strip()
        # Storefronts append their own name after a separator; keep the product part.
        cleaned = re.split(r"\s+[–—|]\s+", cleaned)[0].strip()
        if not cleaned or len(cleaned) < 10 or len(cleaned) > 200:
            continue
        if model_key not in normalise(cleaned):
            continue
        if cleaned.lower() in seen:
            continue
        seen.add(cleaned.lower())
        titles.append(cleaned)

    return titles


# Phrases that appear on anti-bot / CAPTCHA challenge pages (Cloudflare, Akamai,
# etc.) but never on a real product page. Kept specific to avoid false positives
# -- a product page mentioning "cloudflare" in a footer must NOT be flagged.
_BLOCK_PAGE_MARKERS = (
    "just a moment",
    "checking your browser",
    "enable javascript and cookies",
    "verify you are human",
    "attention required",
    "ddos protection by cloudflare",
    "please turn javascript on",
    "access denied",
)


def is_block_page(content: str) -> bool:
    """
    True when scraped text is an anti-bot / CAPTCHA challenge rather than product
    content. Lets the pipeline tell the operator "this site blocked us, paste the
    Details" instead of the misleading "product not listed".
    """
    if not content:
        return False
    lowered = content.lower()
    return any(marker in lowered for marker in _BLOCK_PAGE_MARKERS)


def _clean_html_to_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "header", "footer", "noscript", "svg", "form"]):
        tag.decompose()
    text = soup.get_text(separator="\n")
    lines = [line.strip() for line in text.splitlines()]
    cleaned = "\n".join(line for line in lines if line)
    return cleaned[:_MAX_CLEANED_CONTENT_CHARS]


class PlaywrightEngine:
    async def scrape_url(self, url: str, model_number: str = "") -> ScrapeResult:
        async with async_playwright() as p:
            try:
                browser = await p.chromium.launch(headless=True)
                context = await browser.new_context(
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
                    # A headless 0x0 screen is itself a detection signal; a real
                    # viewport + locale makes the stealth patch below effective.
                    viewport={"width": 1920, "height": 1080},
                    locale="en-US",
                )
                page = await context.new_page()

                # Stealth: hide the headless fingerprint (navigator.webdriver,
                # Chrome runtime, etc.). Lazy + optional: a missing package or API
                # drift degrades to plain Playwright, never crashes the scrape.
                # The tf-playwright-stealth fork installs as the `playwright_stealth`
                # module and exposes stealth_async(page).
                try:
                    from playwright_stealth import stealth_async
                    await stealth_async(page)
                except Exception as e:
                    logger.debug(f"Playwright stealth not applied ({e}); continuing without it.")

                # "networkidle" timed out in real testing against a live product
                # page (ads/analytics/chat widgets keep the network "active"
                # indefinitely on many real sites) -- "domcontentloaded" is what
                # the content actually needs and is far more reliable in practice.
                last_error: Exception | None = None
                for attempt in range(_LOAD_ATTEMPTS):
                    try:
                        await page.goto(url, wait_until="domcontentloaded", timeout=_PAGE_TIMEOUT_MS)
                        last_error = None
                        break
                    except Exception as e:
                        last_error = e
                        logger.warning(
                            f"Page load attempt {attempt + 1}/{_LOAD_ATTEMPTS} failed for {url}: {e}"
                        )
                if last_error is not None:
                    raise last_error

                # Extract content, stripped down to plain readable text
                raw_html = await page.content()
                content = _clean_html_to_text(raw_html)
                links = extract_product_links(raw_html, url, model_number) if model_number else []
                titles = extract_candidate_titles(raw_html, model_number) if model_number else []

                await browser.close()

                return ScrapeResult(
                    url=url,
                    content=content,
                    engine_used="playwright",
                    success=True,
                    product_links=links,
                    candidate_titles=titles,
                )
            except Exception as e:
                logger.error(f"Playwright error scraping {url}: {str(e)}")
                return ScrapeResult(
                    url=url,
                    content="",
                    engine_used="playwright",
                    success=False,
                    error_message=str(e)
                )

async def scrape_with_playwright(url: str, model_number: str = "") -> ScrapeResult:
    """
    Returns the full ScrapeResult (not just text) so callers can follow
    product_links through to the detail page. A failed scrape still returns a
    result object with success=False rather than raising.
    """
    engine = PlaywrightEngine()
    return await engine.scrape_url(url, model_number)
