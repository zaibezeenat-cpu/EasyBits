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


_EMPTY_BRACKETS_RE = re.compile(r"\(\s*\)|\[\s*\]")
_MULTIPLE_SPACES_RE = re.compile(r" {2,}")
_TRAILING_HYPHEN_RE = re.compile(r"[\s-]+$")
_COMMA_RE = re.compile(r"\s*,\s*")


def _sanitize_title(name: str) -> str:
    """
    Boss Rule Step 3 (owner-directed, 2026-08-10): format hygiene a title
    must never violate, applied as a final deterministic pass regardless of
    which inputs produced the string -- cheaper and more reliable than
    trying to guarantee every individual input is already clean.

    - Empty () / [] : never meaningful, only ever noise from a stripped-out
      value upstream. Deliberately only EMPTY brackets -- a bracket with
      real content inside it is a separate, not-yet-reported concern this
      pass does not touch.
    - Double spaces: collapsed to one.
    - A trailing hyphen (with or without trailing whitespace): stripped --
      a dangling "- " at the end reads as an unfinished title.
    - Commas: replaced with a plain SPACE, not the word "and" (reviewed and
      corrected 2026-08-10) -- Rank Math counts focus-keyword occurrences by
      splitting on punctuation, so a comma inside the title can silently
      break that count (Boss Rule #6). A space avoids two real problems
      "and" would cause: several commas in one title ("Kitchen Robot,
      Deluxe, 700W") would otherwise read as spammy repetition ("Kitchen
      Robot and Deluxe and 700W"), and a category that already legitimately
      contains "and" ("Grinder and Blender") would risk being doubled up.
    """
    name = _EMPTY_BRACKETS_RE.sub("", name)
    name = _COMMA_RE.sub(" ", name)
    name = _MULTIPLE_SPACES_RE.sub(" ", name).strip()
    name = _TRAILING_HYPHEN_RE.sub("", name).strip()
    return name


def build_name(
    brand: str,
    capacity: str,
    model: str,
    product_type: str,
    features: list[str] | None = None,
    series: str | None = None,
    wattage: str | None = None,
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

    TWO SPEC SLOTS, INDEPENDENT OF EACH OTHER (owner's written spec plus his
    2026-08-11 correction). The owner's document describes these as two
    "patterns", but they are really two separate slots -- a product can use
    either, both, or neither:

      CAPACITY (Kg, Tons, Liters, Cu Ft) -- a core part of the product's
      identity, so it sits INLINE with no dash, right after the model:
          "Dawlance DW6570 GB 8 Kg Twin Tub Semi Automatic Washing Machine"
          "Haier HRF-418 IPRA 14 Cu Ft Purple Glass Door Smart Inverter Refrigerator"

      WATTAGE -- a technical detail rather than the identity, so it trails
      LAST after a mandatory dash:
          "Anex AG-2098 Deluxe 2 in 1 Vacuum Cleaner - 1500W"
          "Anex AG-3151 Deluxe Kitchen Robot - 700W"

      BOTH, when both are confirmed (owner's real microwave example):
          "Anex AG-9039 25L Deluxe Digital Microwave With Oven - 900W"
      and the same product when no capacity was confirmed:
          "Anex AG-9039 Deluxe Digital Microwave With Oven - 900W"

    Both are CONFIRMED SPEC FACTS rather than harvested marketing words, so
    neither is ever dropped for length the way a `features` entry can be.

    (Two earlier implementations got this wrong and are what this corrects:
    first, wattage was put in capacity's inline slot with no dash for every
    product -- "Anex AG-3151 700W Deluxe Kitchen Robot", neither shape; then
    capacity was briefly treated as excluding wattage entirely, which the
    owner corrected with the microwave examples above.)

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
    # The trailing "- <wattage>" slot, independent of the inline capacity
    # slot -- a product with both keeps both. See the docstring.
    dash_spec = (wattage or "").strip()

    # Identity + series form the part that is never dropped: the series is a
    # proper noun customers search by ("Luxury Ultra"), so it outranks generic
    # feature words when the name has to be shortened.
    # Order is brand -> model -> capacity per the Boss Rule.
    identity = [p for p in (brand, model, capacity) if p and p.strip()]
    if series and series.strip():
        identity.append(series.strip())
    product_type = (product_type or "").strip()

    verified_features = [f.strip() for f in (features or []) if f and f.strip()]
    # Deduplication (owner-reviewed, 2026-08-10): a harvested title-term
    # phrase could independently produce the same value a spec slot already
    # holds (e.g. a scraped title literally contains "700W" as its own
    # n-gram) -- without this, the assembled title would repeat it:
    # "... Deluxe 700W Kitchen Robot - 700W". Exact match only
    # (case-insensitive): a feature merely CONTAINING the wattage string
    # ("700W Turbo Motor") is left alone, since dropping the whole phrase
    # over a partial match would lose real, verified information.
    if dash_spec:
        spec_key = dash_spec.lower()
        verified_features = [f for f in verified_features if f.lower() != spec_key]

    # Same guard for the series, which occupies its own identity slot above.
    # Owner-reported (2026-08-12, live CSV): the exported title read "Anex
    # AG-2098 Deluxe Deluxe -2 in 1 Vacuum Cleaner - 1500W" -- "Deluxe"
    # arrived twice, once as the extracted `series` and once as a harvested
    # feature term, with nothing deduplicating the two against each other.
    if series and series.strip():
        series_key = series.strip().lower()
        verified_features = [f for f in verified_features if f.lower() != series_key]

    # The trailing spec is part of the length budget but is never itself
    # dropped -- it is confirmed data, so features give way to it, not the
    # other way round.
    suffix = f" - {dash_spec}" if dash_spec else ""

    # Longest first: keep as many feature words as fit before the product type.
    # MAX_NAME_LENGTH is checked on the pre-sanitize join -- _sanitize_title
    # only ever shrinks a string (collapsing spaces, stripping stray
    # punctuation), never grows it, so checking before is the conservative,
    # correct order: sanitizing first could hide a candidate that was
    # actually over-length before cleanup.
    for count in range(len(verified_features), -1, -1):
        parts = identity + verified_features[:count] + ([product_type] if product_type else [])
        candidate = " ".join(parts).strip() + suffix
        if len(candidate) <= MAX_NAME_LENGTH or count == 0:
            return _sanitize_title(candidate)

    return _sanitize_title(
        " ".join(identity + ([product_type] if product_type else [])).strip() + suffix
    )


def expand_abbreviation(product_type: str) -> str:
    """
    Expands a shorthand product type to its full form ("AC" -> "Air Conditioner").

    Exposed so callers can normalise a category before building a name, rather
    than silently shipping an abbreviated title.
    """
    return _FORBIDDEN_ABBREVIATIONS.get(product_type.strip().lower(), product_type)


def title_format_violation(name: str) -> str | None:
    """
    Returns a short description of the first Boss Rule Step 3 format
    violation found in `name`, or None when it's clean.

    Defense-in-depth (2026-08-10): `_sanitize_title()` above already
    prevents these at build time, but a Product Name can also be edited by
    hand after generation (the frontend allows this), so
    app/graph/seo_validator.py calls this independently rather than trusting
    the builder was the only path that ever produced the string -- the same
    reason `contains_forbidden_abbreviation` exists as a validator-side
    check alongside this module's own abbreviation avoidance.
    """
    if _EMPTY_BRACKETS_RE.search(name):
        return "contains empty brackets () or []"
    if _MULTIPLE_SPACES_RE.search(name):
        return "contains a double space"
    if _TRAILING_HYPHEN_RE.search(name):
        return "ends with a trailing hyphen"
    if "," in name:
        return "contains a comma (breaks Rank Math's keyword counting)"
    return None


def contains_forbidden_abbreviation(name: str) -> str | None:
    """
    Returns the offending abbreviation when a product name uses one, else None.
    Used by the SEO validator so an abbreviated title is caught before export.
    """
    for abbreviation in _FORBIDDEN_ABBREVIATIONS:
        if re.search(rf"\b{re.escape(abbreviation)}\b", name, flags=re.IGNORECASE):
            return abbreviation
    return None
