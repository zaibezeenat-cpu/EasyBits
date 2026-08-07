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

def assign_prices(price_a: Decimal, price_b: Decimal) -> tuple[Decimal, Decimal | None]:
    """
    Returns (regular_price, sale_price) — the HIGHER value is always the regular
    (struck-through) price and the LOWER is always the sale price.

    WHY THIS IGNORES THE COLUMN LABELS: in the real sheet the column headed
    "Regular Price" actually holds the *selling* price and "Sale Price" holds the
    original higher price -- confirmed against real exported rows (139999/150000
    became Sale=139999, Regular=150000; 199999/220000 became Sale=199999,
    Regular=220000). Trusting the headers publishes the higher number as the sale
    price, i.e. a price INCREASE displayed to customers as a discount. Deriving
    the roles from the values instead makes that class of error impossible
    regardless of how the two columns are filled in or reordered.

    If both values are equal there is no discount, so sale_price is None rather
    than equal-to-regular (WooCommerce renders an equal sale price as no
    discount anyway, and phase1.md's price check requires sale < regular).
    """
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
    "oven toaster": [r"\btoaster\b"],
    "hotplate": [r"\bhot\s*plate\b"],
    "fans": [r"\bceiling\s*fan\b", r"\bpedestal\s*fan\b", r"\bfan\b"],
    "led tv": [r"\bsmart\s*tv\b", r"\btv\b"],
    "vacuum cleaner": [r"\bvacuum\b"],
    "microwave oven": [r"\bmicrowave\b"],
    # Hand-operated food prep. These carry real weight: a hand chopper has no
    # motor, so the electric schema's required wattage can never be found and
    # the product is routed to Manual Review for a fact it does not have.
    #
    # "Hand" alone does not match real titles -- Anex's own page calls the AG-01
    # a "Handy Pull Chopper", where "Handy" is a different word and "Pull" is the
    # actual mechanism. Each pattern below matches a word PRESENT in the title;
    # nothing here deduces a product's nature from its SKU.
    #
    # Both the general and the hand category match such a title, and
    # _most_specific resolves that to the hand one (its words are a strict
    # superset). A plain "Chopper" matches nothing here and stays electric.
    "hand chopper": [
        r"\bhand[\s-]*chopper\b",
        r"\bhandy\b[\w\s-]*\bchopper\b",
        r"\bpull\b[\w\s-]*\bchopper\b",
        r"\bmanual\b[\w\s-]*\bchopper\b",
        r"\bhand[\s-]*held\b[\w\s-]*\bchopper\b",
        r"\bnon[\s-]*electric\b[\w\s-]*\bchopper\b",
    ],
    "hand blender": [
        r"\bhand[\s-]*blender\b",
        r"\bmanual\b[\w\s-]*\bblender\b",
        r"\bhand[\s-]*held\b[\w\s-]*\bblender\b",
    ],
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
    # An immersion/stick blender is HELD in the hand but is very much motorised,
    # so "hand held" alone would wrongly strip its wattage requirement. A stated
    # wattage is decisive either way: a product that draws power has a motor and
    # belongs on the electric category, whatever the marketing copy calls it.
    #
    # Erring toward the electric category is the safe direction -- it keeps the
    # wattage REQUIRED, so a genuine hand-operated product misrouted here stops
    # in Manual Review (visible, correctable via the Category column) instead of
    # silently publishing with a requirement quietly dropped.
    "hand blender": [r"\bimmersion\b", r"\bstick\b", r"\d+\s*(?:W|watts?)\b"],
    "hand chopper": [r"\d+\s*(?:W|watts?)\b"],
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

    When several categories match, the deepest of a specificity chain wins
    ("Hand Chopper" over "Chopper") -- see _most_specific. Anything else
    ambiguous returns None, on purpose: a wrong category produces a wrong
    "Parent > Category" breadcrumb and files the product in the wrong place on
    the live store, which is harder to notice and undo than a row sitting in
    Manual Review. Zero matches also returns None.
    """
    if not product_name or not known_categories:
        return None

    aliases = _DEFAULT_CATEGORY_ALIASES if category_aliases is None else category_aliases
    exclusions = _DEFAULT_CATEGORY_EXCLUSIONS if category_exclusions is None else category_exclusions

    matches = set()
    for category in known_categories:
        patterns = [_derive_name_pattern(category)]
        patterns.extend(aliases.get(category.lower(), []))
        if not any(re.search(p, product_name, re.IGNORECASE) for p in patterns):
            continue
        # The category name is present, but only as a modifier of a different
        # appliance type -- not this product's category.
        if any(
            re.search(p, product_name, re.IGNORECASE)
            for p in exclusions.get(category.lower(), [])
        ):
            continue
        matches.add(category)

    if len(matches) == 1:
        return matches.pop()
    return _most_specific(matches)


def _most_specific(matches: set[str]) -> str | None:
    """Resolves a specificity chain to its deepest category, else None.

    A taxonomy can hold both a general category and a narrower variant of it
    ("Chopper" / "Hand Chopper"). A title naming the specific one necessarily
    contains the general one's name too, so both match and the caller's
    ambiguity guard would reject a title that was in fact perfectly explicit.

    A category is MORE SPECIFIC than another when its words are a strict
    superset of the other's -- "Hand Chopper" over "Chopper". Choosing it is
    reading the title, not deducing past it: the extra word is literally
    present. Word sets, not substrings, so "Chop Saw" and "Chopper" are
    unrelated despite the shared prefix.

    Genuinely unrelated matches ("Blender" and "Chopper" both named) are left
    ambiguous -- resolving those would need information the title does not
    carry, which is the caller's reason for escalating to Manual Review.

    Args:
        matches: Category names that all matched the product title.

    Returns:
        The single deepest category when every match lies on one chain,
        otherwise None.
    """
    if not matches:
        return None

    words = {c: frozenset(c.lower().split()) for c in matches}
    deepest = max(matches, key=lambda c: len(words[c]))
    # Every other match must be a strict subset of the winner; if any is not,
    # the matches are not one chain and the ambiguity is real.
    if all(words[c] < words[deepest] for c in matches if c != deepest):
        return deepest
    return None


# --- Template selection -----------------------------------------------------

def detect_template(status_text: str | None) -> TemplateChoice | None:
    """
    Maps the sheet's free-text Status column to a template:
      "...images FOUND, SO MAKE A DESCRIPTION WITH IMAGE ONE..." -> "A" (zig-zag image grid)
      "no description images here so used no images template"    -> "B" (text only)

    Returns None when the text says neither, so the pipeline's existing
    image_fallback_node decides from the real scraped image count instead. That
    is deliberate: guessing "A" on an ambiguous status emits three <img src="">
    placeholders that ship broken-looking images if nobody fills them in.
    """
    if not status_text:
        return None

    text = status_text.lower()
    # Check the negative first: "no description images" also contains "images".
    if "no image" in text or "no description image" in text or "no images" in text:
        return "B"
    if "images found" in text or "image found" in text:
        return "A"
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
    price_a: Decimal,
    price_b: Decimal,
    warranty_text: str | None = None,
    status_text: str | None = None,
    known_brands: list[str] | None = None,
    known_categories: list[str] | None = None,
    category_parents: dict[str, str] | None = None,
    color: str | None = None,
    variant: str | None = None,
) -> ParsedSheetRow:
    """
    Normalises one spreadsheet row. `price_a`/`price_b` are the two price cells
    in sheet order; their roles are derived from their values, not their headers
    (see assign_prices).

    `known_brands` / `known_categories` come from the live taxonomy tables so
    brand casing is exact and categories are restricted to ones that really
    exist. `category_parents` maps child category name -> parent name (also from
    the categories table) and produces the "Parent > Category" breadcrumb via
    ParsedSheetRow.category_path. Anything that cannot be resolved is left None
    -- check ParsedSheetRow.missing_required() and escalate rather than guessing.
    """
    regular_price, sale_price = assign_prices(price_a, price_b)
    category_name = infer_category(product_name, known_categories or [])

    # SKU = model number + a distinguishing qualifier. The same model ships in
    # several colours, so the bare model number is not unique -- and a duplicate
    # SKU makes WooCommerce OVERWRITE the live product rather than add one.
    # `color` is usually only known after extraction, so it is optional here;
    # the caller can rebuild the SKU with build_sku() once colour is confirmed.
    model_number = extract_sku(product_name)
    sku = build_sku(model_number, color=color, variant=variant) if model_number else None

    return ParsedSheetRow(
        product_name=product_name.strip(),
        sku=sku,
        model_number=model_number,
        brand_name=match_brand(product_name, known_brands or []),
        category_name=category_name,
        category_parent=(category_parents or {}).get(category_name) if category_name else None,
        regular_price=regular_price,
        sale_price=sale_price,
        warranty_phrase=normalise_warranty(warranty_text),
        template_choice=detect_template(status_text),
    )
