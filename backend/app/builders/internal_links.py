"""
Builds the internal and external links Rank Math requires in the description.

Three of its tests depend on links being present:
  * Internal Links          -- at least one link to our own site
  * External Links          -- at least one outbound link
  * DoFollow External Links -- that outbound link must pass link equity

Beyond the score, these are genuinely useful: the category and brand links give
shoppers a route deeper into the catalogue, and the official brand link is a
trust signal.

URL patterns are the live site's, confirmed by the owner:
    https://kiachahiye.com/product-category/home-appliance/
    https://kiachahiye.com/product-category/home-appliance/refrigerator/
    https://kiachahiye.com/product-category/kitchen-appliances/blender/
    https://kiachahiye.com/brand/anex/
"""
import re

SITE_BASE_URL = "https://kiachahiye.com"

# WooCommerce default product permalink base. Change to "/" if the store uses
# root permalinks (products at https://kiachahiye.com/<slug>/).
PRODUCT_PATH = "/product/"

# Rank Math flags an over-long slug/URL. The owner locked the ceiling at 65
# characters for the FULL product URL (slug included), so the slug is trimmed to
# keep the canonical URL within it.
MAX_URL_LENGTH = 65

# Brand-accent colour, matching the rest of the generated markup. Single quotes
# throughout, per the CSV data-integrity rule.
_LINK_STYLE = "color: #561491; text-decoration: underline;"


def slugify(value: str) -> str:
    """
    WordPress-style slug: lowercase, non-alphanumerics collapsed to hyphens.

        "Home Appliance"  -> "home-appliance"
        "Air conditioner" -> "air-conditioner"
        "Kitchen Appliances" -> "kitchen-appliances"
    """
    slug = re.sub(r"[^a-z0-9]+", "-", (value or "").lower()).strip("-")
    return slug


def category_url(category_name: str, parent_name: str | None = None) -> str | None:
    """
    Category archive URL. Sub-categories nest under their parent, matching the
    live site: a child without its parent would 404, so a category with no
    parent is treated as top-level rather than guessed at.
    """
    if (category_name or "").strip().lower() == "manual chopper":
        category_name = "Chopper"
        if not parent_name:
            parent_name = "Kitchen Appliances"
    child = slugify(category_name)
    if not child:
        return None
    parent = slugify(parent_name or "")
    if parent:
        return f"{SITE_BASE_URL}/product-category/{parent}/{child}/"
    return f"{SITE_BASE_URL}/product-category/{child}/"


def brand_url(brand_name: str) -> str | None:
    """Brand archive URL, e.g. https://kiachahiye.com/brand/anex/"""
    slug = slugify(brand_name)
    return f"{SITE_BASE_URL}/brand/{slug}/" if slug else None


def build_product_slug(
    model_number: str, product_type: str | None = None, brand: str = "",
    max_url_length: int = MAX_URL_LENGTH,
) -> str:
    """
    A short, descriptive product slug whose FULL canonical URL stays within
    ``max_url_length`` (Rank Math's URL-length ceiling). The product TITLE can be
    long (Boss Rule, up to 90 chars); the slug is deliberately decoupled and kept
    short -- model number + product type, which is unique and readable
    ("wf-6807-hair-straightener"). The model is never dropped; only trailing words
    are trimmed to fit the budget.
    """
    pt = (product_type or "").strip()
    if pt.lower() == "none":
        pt = ""

    parts = [model_number]
    if pt:
        parts.append(pt)
    elif brand:
        parts.insert(0, brand)

    raw_slug_text = " ".join(parts).strip()
    base_len = len(SITE_BASE_URL) + len(PRODUCT_PATH) + 1  # +1 for the trailing "/"
    budget = max(len(slugify(model_number)) or 1, max_url_length - base_len)

    slug = slugify(raw_slug_text) or slugify(model_number)
    if len(slug) > budget:
        slug = slug[:budget].rstrip("-")
    return slug


def build_canonical_url(slug: str) -> str:
    """Full canonical product URL from a slug: SITE/product/<slug>/."""
    return f"{SITE_BASE_URL}{PRODUCT_PATH}{slug}/" if slug else ""


def _anchor(url: str, text: str, dofollow: bool = True) -> str:
    """
    Builds an anchor tag.

    External links are deliberately dofollow (no rel='nofollow'): Rank Math
    tests specifically for a dofollow outbound link, and a manufacturer's
    official site is exactly the kind of authoritative reference that should
    pass link equity.
    """
    rel = "" if dofollow else " rel='nofollow'"
    target = " target='_blank'" if url.startswith("http") and SITE_BASE_URL not in url else ""
    return f"<a href='{url}' style='{_LINK_STYLE}'{rel}{target}>{text}</a>"


def build_link_block(
    brand_name: str,
    category_name: str,
    parent_category: str | None = None,
    official_brand_domain: str | None = None,
) -> str:
    """
    Renders the link paragraph appended to the product description.

    The external link is omitted entirely when no official domain is configured
    for the brand. That is deliberate: `brand_domain_aliases` starts empty
    because probing likely domains produced confident but wrong matches
    (royal.com.pk is a school, gaba.pk a rug store). A missing external link
    costs one Rank Math test; a link to the wrong company's website is a real
    credibility problem. Populate the table and the link appears automatically.
    """
    links: list[str] = []

    cat_display = "Chopper" if (category_name or "").strip().lower() == "manual chopper" else category_name
    cat_url = category_url(category_name, parent_category)
    if cat_url:
        links.append(f"Browse more {_anchor(cat_url, cat_display)}")

    b_url = brand_url(brand_name)
    if b_url:
        links.append(f"View all {_anchor(b_url, brand_name)} products")

    if official_brand_domain and official_brand_domain.strip():
        # Stored values may be a bare host ("hanco.pk") OR a full URL with a
        # path -- DWP hosts EcoStar and GREE as sections of one site
        # ("https://dwphome.pk/ecostar"), so the path must be preserved or the
        # link lands on the wrong brand's page.
        raw = official_brand_domain.strip()
        url = raw if raw.lower().startswith(("http://", "https://")) else f"https://{raw}"
        links.append(
            "Official brand site: "
            + _anchor(url.rstrip("/"), f"{brand_name} Official", dofollow=True)
        )

    if not links:
        return ""

    return (
        "<p style='margin-top: 25px; font-size: 14px;'>"
        + " &nbsp;|&nbsp; ".join(links)
        + "</p>"
    )
