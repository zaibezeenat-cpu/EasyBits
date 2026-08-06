"""
Adapter for the real input spreadsheet format:

    S.No | Product Name | Regular Price | Sale Price | Warranty | Status

Everything here is deterministic (no LLM) and exists to eliminate specific
mistakes that happen when this sheet is transcribed by hand. Each function
documents the real-world error it prevents.
"""
import re
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel

TemplateChoice = Literal["A", "B"]


class ParsedSheetRow(BaseModel):
    """One input row, normalised into what the pipeline actually needs."""
    product_name: str
    sku: str | None = None
    # The model number the SKU was built from. Exposed because the bulk-import
    # preview needs it: without it the operator cannot tell whether the row was
    # matched to the right product before anything is created.
    model_number: str | None = None
    brand_name: str | None = None
    category_name: str | None = None
    category_parent: str | None = None
    regular_price: Decimal
    sale_price: Decimal | None = None
    warranty_phrase: str | None = None
    template_choice: TemplateChoice | None = None

    @property
    def category_path(self) -> str | None:
        """
        The breadcrumb WooCommerce actually imports: "[Parent] > [Category]",
        e.g. "Home Appliance > Air conditioner".

        Categories are a two-level tree (parent > child), so the child name alone
        is not a valid Categories value -- csv_assembler raises
        CategoryBreadcrumbError without the parent. Returns the bare name only
        when the category genuinely has no parent (a top-level category).
        """
        if not self.category_name:
            return None
        if self.category_parent:
            return f"{self.category_parent} > {self.category_name}"
        return self.category_name

    def missing_required(self) -> list[str]:
        """
        Fields the pipeline cannot run without. Returned so the caller can route
        the row to Manual Review with a precise reason instead of failing deep
        inside the graph with a vague error.
        """
        missing = []
        if not self.sku:
            missing.append("sku (no model number found in product name)")
        if not self.brand_name:
            missing.append("brand (no match against live brand taxonomy)")
        if not self.category_name:
            missing.append("category (could not be inferred unambiguously)")
        return missing


# --- Price assignment -------------------------------------------------------

DEFAULT_MARKUP = Decimal("1.10")


def assign_prices(
    price_a: Optional[Decimal] = None,
    price_b: Optional[Decimal] = None,
    sale_price: Optional[Decimal] = None,
    regular_price: Optional[Decimal] = None,
) -> tuple[Decimal, Optional[Decimal]]:
    """
    Returns (regular_price, sale_price).

    If sale_price is provided:
        - If regular_price is also provided, we use both (ensuring regular > sale).
        - If regular_price is missing, we calculate a markup for it.
    
    Legacy support (price_a / price_b):
    Ignores column labels and uses the HIGHER value as regular price.
    """
    if sale_price is not None:
        if sale_price <= 0:
            raise ValueError(f"Sale price must be positive, got {sale_price}")
        if regular_price is not None:
            if regular_price <= 0:
                raise ValueError(f"Regular price must be positive, got {regular_price}")
            high, low = max(regular_price, sale_price), min(regular_price, sale_price)
            return high, (low if high > low else None)
        else:
            # Auto-calculate markup
            calc_regular = (sale_price * DEFAULT_MARKUP).quantize(Decimal("1.00"))
            return calc_regular, sale_price

    if price_a is None or price_b is None:
        raise ValueError("Must provide either (sale_price) or (price_a and price_b)")

    if price_a <= 0 or price_b <= 0:
        raise ValueError(f"Prices must be positive, got {price_a} and {price_b}")

    high, low = max(price_a, price_b), min(price_a, price_b)
    if high == low:
        return high, None
    return high, low


# --- SKU / model-number extraction ------------------------------------------

# Units that can look like a model token once concatenated ("100L", "1500W").
_UNIT_SUFFIXES = r"(?:L|LTR|LITERS?|KG|TON|TONS|W|KW|V|CU|CUFT|INCH|IN|MM|CM)"
_CAPACITY_LIKE = re.compile(rf"^\d+(?:\.\d+)?{_UNIT_SUFFIXES}$", re.IGNORECASE)


def build_sku(model_number: str, color: str | None = None,
              variant: str | None = None) -> str | None:
    """
    Builds the unique SKU: model number plus a distinguishing attribute.

        build_sku("DBD-1035", color="Glass")   -> "DBD-1035-GLASS"
        build_sku("YL-2037S-B", variant="30L") -> "YL-2037S-B-30L"
        build_sku("DWHJ-8002")                 -> "DWHJ-8002"

    WHY THE QUALIFIER MATTERS: the same model number is sold in several colours
    and finishes, so a bare model number is NOT unique. A duplicate SKU on
    import does not create a second product -- WooCommerce OVERWRITES the
    existing one, silently destroying a live listing. Colour is the primary
    discriminator; `variant` (capacity, finish, series) is the fallback when no
    colour applies.

    An UNKNOWN/unconfirmed qualifier is ignored rather than guessed: a wrong
    qualifier produces an SKU that matches nothing, which is recoverable, while
    a wrongly-shared SKU overwrites live data, which is not.
    """
    if not model_number or not model_number.strip():
        return None

    base = model_number.strip().upper()
    for qualifier in (color, variant):
        if qualifier and qualifier.strip() and qualifier.strip().upper() != "UNKNOWN":
            suffix = re.sub(r"[^A-Za-z0-9]+", "-", qualifier.strip()).strip("-").upper()
            if suffix and suffix not in base:
                return f"{base}-{suffix}"
            return base
    return base


def extract_sku(product_name: str) -> str | None:
    """
    Pulls the model number out of a product name, e.g.
        "Kenwood KLU-12B03S 1.0 Ton Luxury Ultra Inverter AC"  -> "KLU-12B03S"
        "Midea 18HRFN8 Breezeless 1.5 Ton Inverter AC"          -> "18HRFN8"
        "Midea 2 Ton MSEZ2C-24HRFN1 Xtreme Plus Inverter AC"    -> "MSEZ2C-24HRFN1"

    A model token mixes letters and digits and is at least 4 characters long.
    That length floor is deliberate: it rejects short alphanumerics that are
    specs rather than identifiers -- "R32" (refrigerant), "T3" (compressor
    rating) -- which would otherwise be picked up as the SKU. Capacity tokens
    like "100L" or "1500W" are rejected separately by _CAPACITY_LIKE, since they
    clear the length floor but are not identifiers either.

    Returns None when nothing qualifies. The caller must escalate rather than
    invent a SKU -- a wrong SKU either collides with a live product or creates an
    unfindable one, and both are worse than asking a human.
    """
    if not product_name:
        return None

    # Split on whitespace and separators that never appear inside a model number.
    for raw_token in re.split(r"[\s|,/()\[\]]+", product_name):
        token = raw_token.strip().strip("-–—.:;")
        if len(token) < 4:
            continue
        if not (re.search(r"[A-Za-z]", token) and re.search(r"\d", token)):
            continue
        if _CAPACITY_LIKE.match(token):
            continue
        # Model numbers are letters/digits/hyphens only; this drops stray tokens
        # such as "2026)" leftovers or "Heat&Cool2".
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9\-]*", token):
            continue
        return token.upper()

    return None


# --- Brand matching ---------------------------------------------------------

def match_brand(product_name: str, known_brands: list[str]) -> str | None:
    """
    Finds the brand in a product name and returns it in the EXACT casing stored
    in the live taxonomy (e.g. "DAWLANCE", not "Dawlance").

    WHY IT RETURNS THE STORED STRING: phase1.md's Brand Casing Lock requires the
    CSV's Brands column to match the live WooCommerce taxonomy byte-for-byte, and
    csv_assembler raises BrandCasingMismatchError otherwise. Returning the value
    straight from the taxonomy list -- rather than echoing whatever casing the
    sheet happened to use -- satisfies that lock by construction.

    Longest brands are matched first so "Gaba National" is not shadowed by a
    hypothetical "Gaba". Returns None when no brand matches, so the row escalates
    instead of guessing.
    """
    if not product_name or not known_brands:
        return None

    for brand in sorted(known_brands, key=len, reverse=True):
        if re.search(rf"\b{re.escape(brand)}\b", product_name, re.IGNORECASE):
            return brand
    return None


# --- Category inference -----------------------------------------------------

# Extra shorthand that a category's own name does NOT cover -- real product
# titles say "Inverter AC", never "Air conditioner". These are ALIASES ONLY:
# they are additive, never the sole source of matching, so a category added
# through the Taxonomy Manager still works without any code change here (it is
# matched by its own name via _derive_name_pattern below).
#
# Keyed by lowercased category name so it stays aligned with the DB regardless
# of stored casing.
_DEFAULT_CATEGORY_ALIASES: dict[str, list[str]] = {
    "air conditioner": [r"\bAC\b", r"\bsplit\s*ac\b"],
    "refrigerator": [r"\bfridge\b"],
    "washing machine": [r"\bwasher\b"],
    "deep freezer": [r"\bfreezer\b"],
    "electric kettle": [r"\bkettle\b"],
    "oven toaster": [r"\boven\s*toaster\b"],
    "toaster": [r"\btoaster\b"],
    "hotplate": [r"\bhot\s*plate\b"],
    "fans": [r"\bceiling\s*fan\b", r"\bpedestal\s*fan\b", r"\bfan\b"],
    "led tv": [r"\bsmart\s*tv\b", r"\btv\b"],
    "vacuum cleaner": [r"\bvacuum\b"],
    "microwave oven": [r"\bmicrowave\b"],
    "grinder": [r"\bgrinder\b"],
    "mixer": [r"\bbeater\b", r"\begg\s*beater\b", r"\bhand\s*mixer\b"],
    "chopper": [r"\bmeat\s*chopper\b", r"\bfood\s*chopper\b"],
    "manual chopper": [r"\bslicer\b", r"\bcutter\b", r"\bwonder\b", r"\bmanual\s*chopper\b", r"\bpull\s*chopper\b"],
    "garment steam iron": [r"\biron\b", r"\bsteam\s*iron\b"],
    "air fryer": [r"\bfryer\b", r"\bair\s*fryer\b"],
    "food processor": [r"\bprocessor\b"],
    "sandwich maker": [r"\bsandwich\b"],
    "roti maker": [r"\broti\b"],
    "pizza pan": [r"\bpizza\b"],
}


# Guard for categories whose NAME is also a common adjective on other appliances
# ("Inverter AC", "Inverter Refrigerator"). Such a category matches every product
# that merely mentions the word, so the ambiguity guard would escalate all of
# them. Meaning: "drop this category from the matches IF any of these other terms
# are also present, because there the word is a modifier, not the product type."
#
# THE USER OWNS THE CATEGORY TREE and maintains it in the frontend Taxonomy
# Manager. This default is deliberately EMPTY so nothing here presumes what their
# categories are -- entries only ever take effect if a category of that name
# actually exists. Pass `category_exclusions` (later: a DB column edited in the
# frontend) to add a rule when a genuinely adjective-like category is created.
#
# Keyed by lowercased category name.
_DEFAULT_CATEGORY_EXCLUSIONS: dict[str, list[str]] = {
    "chopper": [r"\bmanual\b", r"\bpull\b", r"\bhandy\b", r"\bcutter\b", r"\bslicer\b"],
}


def _derive_name_pattern(category_name: str) -> str:
    """
    Builds a match pattern from the category's own name, tolerating flexible
    whitespace ("Air conditioner" also matches "AirConditioner"/"air  conditioner").

    This is what keeps category inference DYNAMIC: any category the user adds in
    the frontend Taxonomy Manager becomes matchable immediately, with no code
    change and no redeploy.
    """
    return r"\b" + r"\s*".join(re.escape(part) for part in category_name.split()) + r"\b"


def infer_category(
    product_name: str,
    known_categories: list[str],
    category_aliases: dict[str, list[str]] | None = None,
    category_exclusions: dict[str, list[str]] | None = None,
    top_level_categories: list[str] | None = None,
) -> str | None:
    """
    Infers the category from the product name, restricted to categories that
    actually exist in the live taxonomy (`known_categories` comes from the
    categories table, so it reflects whatever the user has configured).

    Matching is the union of two sources:
      1. the category's own name, derived automatically -- so new categories
         added via the frontend work with no code change;
      2. optional aliases for shorthand a name can't cover ("AC", "fridge").
         Defaults to _DEFAULT_CATEGORY_ALIASES; pass `category_aliases` to
         override from the database once that column exists.

    A matched category is then DROPPED if its exclusion patterns also appear --
    that is how "Inverter" stops hijacking every "Inverter AC" (see
    _DEFAULT_CATEGORY_EXCLUSIONS).

    Fallback behaviour (no LLM, no escalation):
      - Exactly 1 sub-category match → return it (normal path).
      - 0 or multiple sub-category matches → try matching top_level_categories
        (e.g. "Kitchen Appliances") by name/alias the same way. If exactly 1
        top-level matches → return it. This means a product like "Potato Cutter"
        that has no specific sub-category is filed under the correct top-level
        (Kitchen Appliances) rather than escalated. The category_spec_schemas
        table must have a row for every top-level that serves as a catch-all.
      - Still no match → return None (caller can LLM-fallback or escalate).
    """
    if not product_name or not known_categories:
        return None

    aliases = _DEFAULT_CATEGORY_ALIASES if category_aliases is None else category_aliases
    exclusions = _DEFAULT_CATEGORY_EXCLUSIONS if category_exclusions is None else category_exclusions

    def _match_against(candidates: list[str]) -> set[str]:
        found: set[str] = set()
        for category in candidates:
            patterns = [_derive_name_pattern(category)]
            patterns.extend(aliases.get(category.lower(), []))
            if not any(re.search(p, product_name, re.IGNORECASE) for p in patterns):
                continue
            if any(
                re.search(p, product_name, re.IGNORECASE)
                for p in exclusions.get(category.lower(), [])
            ):
                continue
            found.add(category)
        return found

    # --- Pass 1: sub-categories (or all known_categories when top_level not split) ---
    sub_categories = [
        c for c in known_categories
        if not top_level_categories or c not in top_level_categories
    ]
    matches = _match_against(sub_categories)
    if len(matches) == 1:
        return matches.pop()
    elif len(matches) > 1:
        # If one match is a more specific variant of another (e.g. "Hand Mixer" vs "Mixer"),
        # select the longest, most specific sub-category match.
        sorted_matches = sorted(matches, key=len, reverse=True)
        longest = sorted_matches[0]
        if all(shorter.lower() in longest.lower() for shorter in sorted_matches[1:]):
            return longest

    # --- Pass 2: top-level fallback ---
    # If 0 or multiple sub-categories match, try the top-level names.
    # A product with no specific sub-category (e.g. "Potato Cutter") gets
    # filed under the best top-level (e.g. "Kitchen Appliances") rather than
    # going to LLM or Manual Review.
    if top_level_categories:
        top_matches = _match_against(top_level_categories)
        if len(top_matches) == 1:
            return top_matches.pop()

    return None


# --- Template selection -----------------------------------------------------

def detect_template(status_text: str | None) -> TemplateChoice | None:
    """
    Maps the sheet's free-text Status column to a template:
      "...no image description template..." -> "A" (text only)
      "...image description template..." -> "B" (zig-zag image grid)

    Returns None when the text says neither, so the pipeline's existing
    image_fallback_node decides from the real scraped image count instead.
    """
    if not status_text:
        return None

    text = status_text.lower().strip()
    
    # Support exact letters A/B for shorthand
    if text == "a": return "A"
    if text == "b": return "B"
    
    # Check the negative first: "no image" also contains "image".
    if "no image" in text:
        return "A"
    if "image" in text:
        return "B"
    return None


# --- Warranty ---------------------------------------------------------------

def normalise_warranty(warranty_text: str | None) -> str | None:
    """
    The sheet's Warranty column is the authoritative per-product warranty and
    flows into warranty_override, which writer_node prefers over the
    warranty_matrix lookup. Only whitespace is normalised -- the wording is NOT
    rewritten, because the exact phrase has to match across all four places it
    appears (specs row, FAQ 5, short description, meta description) and any
    "tidying" here would silently break that consistency check.
    """
    if not warranty_text or not warranty_text.strip():
        return None
    return re.sub(r"\s+", " ", warranty_text).strip()


# --- Row parsing ------------------------------------------------------------

def parse_sheet_row(
    product_name: str,
    price_a: Decimal | None = None,
    price_b: Decimal | None = None,
    sale_price: Decimal | None = None,
    regular_price: Decimal | None = None,
    warranty_text: str | None = None,
    status_text: str | None = None,
    known_brands: list[str] | None = None,
    known_categories: list[str] | None = None,
    category_parents: dict[str, str] | None = None,
    top_level_categories: list[str] | None = None,
    color: str | None = None,
    variant: str | None = None,
    brand_override: str | None = None,
    model_number_override: str | None = None,
) -> ParsedSheetRow:
    """
    Normalises one spreadsheet row. `price_a`/`price_b` are the two price cells
    in legacy sheet order; newer formats use `sale_price` directly.
    """
    regular_price_val, sale_price_val = assign_prices(
        price_a=price_a,
        price_b=price_b,
        sale_price=sale_price,
        regular_price=regular_price,
    )
    category_name = infer_category(
        product_name,
        known_categories or [],
        top_level_categories=top_level_categories,
    )

    resolved_brand = None
    if brand_override:
        resolved_brand = match_brand(brand_override, known_brands or []) or brand_override.strip()
    if not resolved_brand:
        resolved_brand = match_brand(product_name, known_brands or [])

    extracted_model = model_number_override.strip() if model_number_override else extract_sku(product_name)
    sku = build_sku(extracted_model, color=color, variant=variant) if extracted_model else None

    return ParsedSheetRow(
        product_name=product_name.strip(),
        sku=sku,
        model_number=extracted_model,
        brand_name=resolved_brand,
        category_name=category_name,
        category_parent=(category_parents or {}).get(category_name) if category_name else None,
        regular_price=regular_price_val,
        sale_price=sale_price_val,
        warranty_phrase=normalise_warranty(warranty_text),
        template_choice=detect_template(status_text),
    )

