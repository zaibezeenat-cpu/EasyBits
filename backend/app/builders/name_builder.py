import re

# Category words that must NEVER be abbreviated in a product name (Boss Rule).
# Shoppers scan for the full type, and Rank Math matches the keyword phrase
# verbatim -- "AC" and "Air Conditioner" are different keywords entirely.
_FORBIDDEN_ABBREVIATIONS = {
    "ac": "Air Conditioner",
    "fridge": "Refrigerator",
    "washer": "Washing Machine",
    "microwave": "Microwave Oven",
    "dispenser": "Water Dispenser",
}

# CAUTION -- this limit is the product TITLE length, which is NOT the same as
# the URL slug length, and the two must not be conflated again:
#
#   * The owner's updated Boss Rule example --
#       "Haier HRF-246 EPR 10 Cu Ft LVS E-Star Black Glass Door Non Inverter
#        Refrigerator"
#     -- is 80 characters. The boss supplied this as the canonical title, so
#     the title limit has to admit it; an earlier 70 cap silently dropped its
#     trailing spec words.
#
#   * Rank Math still fails a URL/SLUG over 75 characters. If WooCommerce
#     derives the slug from an 80-char name, that test fails and the score is
#     not 100. THEREFORE the slug MUST be set independently of the title -- a
#     short "brand-model" slug (e.g. "haier-hrf-246-epr") -- rather than left to
#     auto-generate. That decoupling is a deliberate open item (the current CSV
#     has no slug column yet); see the handover notes. Do not "fix" this by
#     shrinking the title back below 75, which would violate the Boss Rule.
MAX_NAME_LENGTH = 90


def _strip_trailing_zeros(match: re.Match) -> str:
    """
    '1.0' -> '1', '1.00' -> '1', but '1.5' stays '1.5'.

    Boss Rule: a whole-number capacity is written "1 Ton", never "1.0 Ton".
    Genuine fractions like 1.5 Ton are meaningful and are preserved exactly.
    """
    number = match.group(0)
    if "." not in number:
        return number
    trimmed = number.rstrip("0").rstrip(".")
    return trimmed or "0"


def _clean_capacity(capacity: str) -> str:
    """
    Normalises capacity wording:
        '1.0 Ton'     -> '1 Ton'      (trailing zero dropped)
        '1.00 Ton'    -> '1 Ton'
        '1.5 Ton'     -> '1.5 Ton'    (real fraction preserved)
        '30 Liters'   -> '30L'
    """
    # Drop trailing zeros on ANY decimal first, so "1.0"/"1.00" both become "1"
    # regardless of which unit (or no unit) follows.
    capacity = re.sub(r"\d+\.\d+", _strip_trailing_zeros, capacity)
    capacity = re.sub(r"(\d+)\s*Liters?\b", r"\1L", capacity, flags=re.IGNORECASE)
    capacity = re.sub(r"(\d+)\s*L(?![a-zA-Z])", r"\1L", capacity, flags=re.IGNORECASE)
    capacity = re.sub(r"(\d+(?:\.\d+)?)\s*Ton\b", r"\1 Ton", capacity, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", capacity).strip()


def build_name(
    brand: str,
    capacity: str,
    model: str,
    product_type: str,
    features: list[str] | None = None,
    series: str | None = None,
) -> str:
    """
    Builds the product title using the Boss Rule (updated 2026-07-22):

        [Brand] [Model] [Variant/Capacity] [Series/Features...] [Full Product Type]

        e.g. "Haier HRF-246 EPR 10 Cu Ft LVS E-Star Black Glass Door Non Inverter Refrigerator"
                    ^model^     ^capacity^  ^series^   ^features...^          ^full type^

    MODEL NOW COMES BEFORE CAPACITY. The earlier rule put capacity first
    ("Kenwood 1 Ton KLU-12B03S ..."); the owner changed this so the model
    number leads, immediately after the brand. The `capacity`/`model` PARAMETER
    order is unchanged for callers -- only the assembled order changed -- so
    that the two are impossible to swap at the call site by mistake.

    THE FULL PRODUCT TYPE ALWAYS COMES LAST. The written Boss Rule lists the
    type before the series, but every real exported title places it at the end,
    and the examples win: "...Refrigerator Non Inverter Black Glass Door"
    buries the category mid-phrase and reads wrong. Ending on the searched term
    ("...Non Inverter Refrigerator") is also the stronger keyword position.

    `series` is the manufacturer's product line ("Luxury Ultra", "Titan") and is
    distinct from `features` ("Inverter Split"), so it is passed separately
    rather than mixed into the feature list -- it is a proper noun and must not
    be dropped for length before the features are.

    (An earlier draft appended features after a dash -- "... Air Conditioner -
    Heat & Cool" -- which split the phrase and matched no real exported title.)

    Three hard constraints, all deliberate:

    1. The product type is NEVER abbreviated. "Air Conditioner" and "AC" are
       different keyword phrases to Rank Math, and the full form is what
       shoppers scan for.

    2. `features` must already be VERIFIED against the specific SKU. This
       function will not invent them -- passing an unverified feature here puts
       a false claim in the product title, the most visible place a wrong
       specification can appear. Callers pass only confirmed extraction values
       (series name, compressor type, cooling mode, finish).

    3. Features are dropped one at a time (last first) when the name exceeds
       MAX_NAME_LENGTH. The identifying part -- brand, capacity, model, type --
       is never truncated, because a cut-off model number makes the product
       unfindable while a missing feature word only makes the title shorter.
    """
    capacity = _clean_capacity(capacity or "")
    # Identity + series form the part that is never dropped: the series is a
    # proper noun customers search by ("Luxury Ultra"), so it outranks generic
    # feature words when the name has to be shortened.
    # Order is brand -> model -> capacity per the updated Boss Rule.
    identity = [p for p in (brand, model, capacity) if p and p.strip()]
    if series and series.strip():
        identity.append(series.strip())
    product_type = (product_type or "").strip()

    verified_features = [f.strip() for f in (features or []) if f and f.strip()]

    # Longest first: keep as many feature words as fit before the product type.
    for count in range(len(verified_features), -1, -1):
        parts = identity + verified_features[:count] + ([product_type] if product_type else [])
        candidate = " ".join(parts).strip()
        if len(candidate) <= MAX_NAME_LENGTH or count == 0:
            return candidate

    return " ".join(identity + ([product_type] if product_type else [])).strip()


def expand_abbreviation(product_type: str) -> str:
    """
    Expands a shorthand product type to its full form ("AC" -> "Air Conditioner").

    Exposed so callers can normalise a category before building a name, rather
    than silently shipping an abbreviated title.
    """
    return _FORBIDDEN_ABBREVIATIONS.get(product_type.strip().lower(), product_type)


def contains_forbidden_abbreviation(name: str) -> str | None:
    """
    Returns the offending abbreviation when a product name uses one, else None.
    Used by the SEO validator so an abbreviated title is caught before export.
    """
    for abbreviation in _FORBIDDEN_ABBREVIATIONS:
        if re.search(rf"\b{re.escape(abbreviation)}\b", name, flags=re.IGNORECASE):
            return abbreviation
    return None
