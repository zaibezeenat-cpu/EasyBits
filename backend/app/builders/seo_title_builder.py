"""
V3.0 Production CSV Blueprint — Universal "Boss Title Rule" SEO title builder.

The SEO title is deterministic, NOT LLM-generated. This guarantees 100/100
Rank Math title compliance every time (no LLM drift, no missing suffix).

One universal pattern, applied across every registered category:
   "[Brand] [Capacity] [Series] [SKU] [Premium Category Suffix]"
   e.g. "Midea 1.5 Ton Breezeless MSCB1CU-18HRFN8 DC Inverter Heat & Cool Split Air Conditioner"
   e.g. "Dawlance 30L Cooking Series DW-133-RG Digital Grill Microwave Oven"
   e.g. "Haier 14 Cu Ft Glass Door HRF-398 Inverter Direct Cool Refrigerator"

Any category NOT yet registered here falls back to the universal power-word
format ("[Focus Keyword] | Buy Smart") rather than guessing a suffix — add
its real category descriptor below as soon as it's confirmed, same as a
Taxonomy Manager entry: this dict is the single source of truth, edited here
(not in the LLM prompt) precisely so the title can never drift per-product.
"""

CATEGORY_TITLE_DESCRIPTORS: dict[str, str] = {
    "Air conditioner": "DC Inverter Heat & Cool Split Air Conditioner",
    "Microwave Oven": "Digital Grill Microwave Oven",
    "Refrigerator": "Inverter Direct Cool Refrigerator",
    "Washing machine": "Fully Automatic Top Load Washing Machine",
    "Air cooler": "Inverter Room Air Cooler",
    "Air Purifier": "HEPA Air Purifier",
    "Deep Freezer": "Inverter Deep Freezer",
    "Fans": "High Speed Ceiling Fan",
    "Geyser": "Instant Gas Water Geyser",
    "Heater": "Room Gas Heater",
    "Vacuum Cleaner": "Bagless Vacuum Cleaner",
    "Water Dispenser": "Hot & Cold Water Dispenser",
    "Air Fryer": "Digital Air Fryer",
    "Blender": "Multi-Speed Blender",
    "Coffee Maker": "Automatic Drip Coffee Maker",
    "Electric Kettle": "Cordless Electric Kettle",
    "Hotplate": "Double Burner Hotplate",
    "Oven Toaster": "Digital Oven Toaster",
}

POWER_WORD_SUFFIX = "Buy Smart"


def build_seo_title(brand: str, capacity: str, series: str, sku: str, category_name: str, focus_keyword: str) -> str:
    """
    Builds the Rank Math SEO title: "[Product Name] | Buy Smart".

    WHY THE CATEGORY-DESCRIPTOR VERSION WAS REMOVED (measured, not assumed):
    it built a DIFFERENT string that inserted words into the middle of the
    product name --
        name  : DAWLANCE DBD-1035 Glass Door Water Dispenser
        title : DAWLANCE DBD-1035 Glass Door Hot & Cold Water Dispenser
    -- which splits the keyword phrase, so Rank Math's "Focus Keyword in SEO
    Title" test FAILS, and with it Sentiment and Power Words (a descriptor
    carries neither). Three of the four title tests lost, from one rule.

    Appending the suffix instead keeps the product name intact and verbatim, so
    the primary focus keyword is always present. Confirmed across every real
    exported CSV supplied by the site owner (Kenwood, Midea x2, Dawlance x4),
    all of which use exactly this format and land at 55-61 characters -- inside
    Google's ~60-character display limit.

    The descriptor approach was also an accuracy risk: "Digital Oven Toaster"
    asserted a feature the product's own spec sheet never confirmed.

    `brand`, `capacity`, `series`, `sku` and `category_name` are retained for
    signature compatibility with existing callers; the product name already
    contains them.
    """
    return f"{focus_keyword} | {POWER_WORD_SUFFIX}"


def build_focus_keyword_field(primary_keyword: str, secondary_keywords: list[str]) -> str:
    """
    V3.0 correction: Rank Math's real "Focus Keyword" field natively supports a
    primary keyword plus secondary/related keywords (confirmed directly from the
    live Rank Math panel UI -- it scores "Keyword Density... Focus Keyword AND
    combination"). The earlier "exactly one keyword, no comma-stacking" lock was
    wrong. This combines the deterministic primary keyword (the Product Name)
    with the Writer's 3 LSI keywords -- the SAME 3 keywords already required to
    appear as plain text in the body/alt-text, so nothing new is generated here,
    just assembled into the format Rank Math actually expects.
    """
    # De-duplicate: the Writer sometimes lists the product name itself as an LSI
    # keyword, which produced "Name, Name, ..." in the field. Keep the primary
    # once, then only secondaries not already present (case-insensitive).
    primary = (primary_keyword or "").strip()
    parts = [primary] if primary else []
    seen = {primary.lower()}
    for k in secondary_keywords:
        k = k.strip()
        if k and k.lower() not in seen:
            parts.append(k)
            seen.add(k.lower())
    return ", ".join(parts)


def title_ends_with_power_word(title: str, category_name: str) -> bool:
    """
    Check used by seo_validator.py: the SEO title must end with the power-word
    suffix. "Smart" is what satisfies Rank Math's Power Words and Sentiment
    title tests, so its absence costs two checks outright.
    """
    return title.rstrip().endswith(POWER_WORD_SUFFIX)


def seo_title_contains_focus_keyword(title: str, focus_keyword: str) -> bool:
    """
    Rank Math's highest-weighted Basic SEO test: the primary focus keyword must
    appear in the SEO title verbatim. Broken out as its own check because the
    previous title builder silently failed it on every product.
    """
    if not title or not focus_keyword:
        return False
    return focus_keyword.strip().lower() in title.lower()
