"""Product matching: title normalisation, 4-slot attribute extraction, and the
negative-collision referee that decides EXACT / BASE-FALLBACK / REJECT.

Architecture (one implementation per concept, zero duplicated rule blocks)
-------------------------------------------------------------------------
1. ``Vocabulary``      -- the only place domain data lives (colours, capacities,
                          tokens, category phrases).  Everything else derives from it.
2. ``Text``            -- pure string normalisation primitives (safeguard masking,
                          technical slashes, screen units, marketplace noise).
3. ``Tokens``          -- predicate functions answering "what kind of token is this?".
4. ``Expansion``       -- cartesian branch + multi-variant slash expansion.
5. ``Extraction``      -- ``extract_search_query_and_model`` / ``extract_product_slots``.
6. ``SearchPatterns``  -- tiered waterfall query generation (ADR-001).
7. ``Referee``         -- a *declarative* guard table.  Each guarded facet is one row;
                          a single loop turns rows into collisions (REJECT) or
                          omissions (BASE fallback).  Adding a facet = adding a row.
8. ``StrictMatcher``   -- the legacy boolean ``is_strict_model_match`` contract.

Verdict contract (ADR-002, Category 1 / Category 2 modifiers)
-------------------------------------------------------------
* EXACT  (``is_match=True``)  -- anchor matched, zero guarded-facet collisions.
* BASE   (``is_base_match=True``) -- the *same* physical base model, but the market
  listing omitted a modifier the catalog asked for.  Downstream reprices against the
  base model and **must** surface a cross-check notice.
* REJECT -- anchor mismatch or a contradicting guarded facet.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from dataclasses import replace as _replace
from typing import Any

# =============================================================================
# 0. DATA MODEL
# =============================================================================


@dataclass
class GuardedFacets:
    """Zero-tolerance guarded attributes for strict variant collision protection."""

    capacity: str | None = None  # e.g. "1.5T", "12KG", "50INCH"
    tub_series: str | None = None  # e.g. "WB", "GB"
    color_family: str | None = None  # One of the 9 normalized color families
    color_raw: str | None = None  # Original matched color text
    color_shade: str | None = None  # Shade modifier of the colour: SMOKE, RUBY…
    door_finish: str | None = None  # Hardware finish: 'GD' (Glass Door) vs 'INOX'
    cool_only: bool | None = None  # True if strictly cooling-only AC model
    heat_and_cool: bool | None = None  # True if Heat & Cool AC model
    door_type: str | None = None  # Hardware door structure: 'SD' vs 'DD'
    is_inverter: bool | None = None  # True if Inverter, False for Non-Inverter
    variant_tag: str | None = None  # Parenthesised/glued finish-variant tag: '(G)', '(OW)'…
    capabilities: set[str] = field(default_factory=set)  # Additive hardware codes


@dataclass
class ProductSlots:
    """4-Slot structural attribute representation of a product title (ADR-002)."""

    anchor: str  # Primary invariant alphanumeric model code (e.g. '120-826S6')
    series: str  # Series extracted via residual subtraction (e.g. 'MAGNA', 'PRIMA')
    guarded_facets: GuardedFacets
    residuals: list[str] = field(default_factory=list)  # Soft modifiers: 'GC', etc.


# Verdict tiers -- the single vocabulary every consumer (scraper, pipeline,
# range pipeline) uses to decide whether a cross-check notice is owed.
TIER_EXACT = "EXACT"
TIER_BASE = "BASE"
TIER_REJECT = "REJECT"


@dataclass
class MatchDecision:
    """Verdict plus audit trail from the negative-collision referee."""

    is_match: bool
    reason: str
    target_slots: ProductSlots | None = None
    candidate_slots: ProductSlots | None = None
    is_base_match: bool = False
    missing_modifier: str | None = None

    @property
    def tier(self) -> str:
        """EXACT / BASE / REJECT -- one accessor so callers never re-derive it."""
        if self.is_match:
            return TIER_EXACT
        return TIER_BASE if self.is_base_match else TIER_REJECT

    @property
    def usable(self) -> bool:
        """True when the offer may be used at all (exact or base-fallback)."""
        return self.is_match or self.is_base_match


# =============================================================================
# 1. VOCABULARY  (single source of truth -- nothing below hardcodes these again)
# =============================================================================

# --- Category 1 modifiers: direct match when the market omits them ------------
# Marketplace sellers routinely omit these (a Single Door fridge is often listed
# without "SD").  Target has it + candidate omits it -> EXACT match, no warning.
# Target has it + candidate has the opposing code -> hard collision.
CATEGORY_1_DIRECT_MATCH_MODIFIERS: set[str] = {"SD"}

# --- 9 normalized color families (ADR-002) ------------------------------------
COLOR_FAMILIES: dict[str, list[str]] = {
    "White": ["MILKY WHITE", "PEARL WHITE", "WHITE", "MILKY", "IVORY"],
    "Black": ["PIANO BLACK", "MATTE BLACK", "MIDNIGHT BLACK", "BLACK", "DARK", "MIDNIGHT"],
    "Grey / Silver": [
        "METALLIC GREY", "DARK METALLIC", "METALLIC GRAY", "STAINLESS STEEL", "INOX",
        "S.S", "GREY", "GRAY", "SILVER", "METALLIC", "STEEL", "TITANIUM", "GRAPHITE",
        "PLATINUM",
    ],
    "Red / Maroon": ["RED", "MAROON", "BURGUNDY", "RUBY", "CRIMSON", "CORAL"],
    "Gold / Bronze / Copper": [
        "ROSE GOLD", "CLASSIC GOLD", "GOLD", "CHAMPAGNE", "BRONZE", "COPPER",
    ],
    "Brown / Wood": ["BROWN", "CHOCOLATE", "WOOD", "WALNUT", "TEAK"],
    "Blue": ["ROYAL BLUE", "SKY BLUE", "NAVY BLUE", "BLUE", "NAVY"],
    "Green": ["GREEN", "EMERALD", "OLIVE"],
    "Purple / Pink": ["PURPLE", "VIOLET", "PINK"],
}

# Single-letter color suffix codes glued to model codes (12AITH21W -> W)
COLOR_SUFFIX_MAP: dict[str, str] = {
    "W": "White",
    "B": "Black",
    "D": "Black",
    "C": "Gold / Bronze / Copper",
    "S": "Grey / Silver",
    "G": "Grey / Silver",
    "R": "Red / Maroon",
    "P": "Purple / Pink",
}

# --- Non-SKU stop tokens ------------------------------------------------------
NON_SKU_TOKENS: set[str] = {
    "4K", "8K", "A+", "AA", "AA+", "AAA", "AAA+", "AC", "AIR", "AIRFRYER", "ALL", "ALSO",
    "AND", "ANDROID", "AS", "AT", "AUTO", "BAG", "BAR", "BASE", "BEAM", "BEST", "BIG",
    "BLENDER", "BODY", "BOX", "BUY", "BY", "CAP", "CARD", "CARE", "CFT", "CHOPPER", "CLEAR",
    "CM", "COLD", "CONTROL", "COOL", "CORD", "CU", "CURTAIN", "DARK", "DAY", "DC", "DEEP",
    "DOOR", "DOT", "DOWN", "DROP", "DRY", "DRYER", "EACH", "EASY", "EVEN", "EVER", "FAST",
    "FEET", "FHD", "FI", "FINE", "FIT", "FLAT", "FOOT", "FOR", "FREE", "FRIDGE", "FROM",
    "FRONT", "FT", "FULL", "GAS", "GM", "GOLD", "GOOD", "GOOGLE", "HAND", "HARD", "HD",
    "HEAD", "HEAT", "HEATER", "HIGH", "HOLD", "HOME", "HOSE", "HOT", "HUB", "IN", "INCH",
    "INCHES", "JUST", "KEEP", "KETTLE", "KG", "LEAD", "LED", "LESS", "LID", "LINE", "LITE",
    "LOAD", "LOCK", "LOOK", "LOW", "LTR", "LVS", "MAKE", "MANUAL", "MINI", "MINIBAR", "MM",
    "MODEL", "MORE", "MOVE", "NEW", "NO", "OF", "OFF", "OIL", "OLED", "ON", "ONE", "ONLY",
    "OPAQUE", "OPEN", "OR", "OUT", "OVEN", "OVER", "PACK", "PART", "PAY", "PIPE", "PLUG",
    "PULL", "PURE", "PURIFIER", "PUSH", "QLED", "QUAD", "REAR", "REF", "REFRIGERATOR", "ROOM",
    "RUN", "SAFE", "SALE", "SAVE", "SAVEIN", "SEMI", "SERIES", "SET", "SETS", "SHUT", "SIDE",
    "SIX", "SIZE", "SLIM", "SMART", "SOFT", "SOLUTION", "SPIN", "SPLIT", "STOP", "TAP",
    "TAPS", "TEN", "THE", "TIME", "TO", "TON", "TONS", "TOP", "TRIP", "TRUE", "TUB", "TUBE",
    "TURN", "TV", "TWIN", "TWO", "TYPE", "UHD", "UNIT", "UPTO", "USE", "VERY", "W/O", "WALL",
    "WASH", "WASHER", "WELL", "WET", "WI", "WIDE", "WIRE", "WITH", "YEAR", "ΤΟN",
}

# --- Genuine sub-series differentiators (a missing one is a real difference) --
GENUINE_SUB_SERIES_TOKENS: set[str] = {
    "PRO", "PLUS", "MAX", "ULTRA", "CLASSIC", "ELEGANT", "PRIMA", "X", "LITE",
    "SUPER", "TOUCH",
}

ROOT_COLORS: set[str] = {
    "WHITE", "BLACK", "GREY", "GRAY", "SILVER", "RED", "BLUE", "GREEN", "GOLD",
    "BROWN", "PINK", "PURPLE", "MILKY", "DARK", "MAROON", "BURGUNDY",
}

# --- Category phrases ---------------------------------------------------------
# One tuple, compiled once.  Anything in here is *never* product identity, so it
# can never leak into the `series` slot.  (BUG FIX: "FULLY AUTOMATIC" / "SEMI
# AUTOMATIC" / "TOP LOAD" used to survive into `series` and turn every real
# marketplace listing into a hard reject -- see docs/validation-report.md RC-1.)
_CATEGORY_PHRASES: tuple[str, ...] = (
    # form factor / appliance kind
    r"AWM", r"AUTO\s+W/M", r"FRONT\s+LOAD(?:\s+W/M)?", r"TOP\s+LOAD", r"W/M",
    r"WASHING\s+MACHINE", r"AIR\s+CONDITIONER", r"M/OVEN", r"M/O", r"MWO", r"D/F",
    r"R/F", r"W/D", r"SPLIT\s+AC", r"SPLIT", r"FLOOR(?:\s+STANDING)?",
    r"DISHWASHER", r"SPINNER", r"DRYER",
    # standalone category nouns (already covered in compounds such as
    # "WASHING MACHINE", but they reach the series slot on their own too)
    r"MACHINE", r"FREEZER", r"CONDITIONER", r"TOASTER", r"GRINDER", r"JUICER",
    r"KETTLE", r"COOLER", r"FAN", r"COOKER", r"CHIMNEY", r"GEYSER", r"TELEVISION",
    r"WASHER", r"LAUNDRY", r"CLOTHES",
    r"AIR\s*CURTAIN", r"AIR\s*COOLER", r"AIR\s*FRYER", r"WATER\s+HEATER",
    r"WATER\s+DISPENSER", r"WATER\s+PURIFIER", r"INSECT\s+KILLER", r"JUG\s+KETTLE",
    r"HOT\s+PLATE", r"CHOPPER", r"BLENDER", r"IRON", r"LED", r"MICROWAVE", r"OVEN",
    r"SANDWI?T?CH\s+MAKER",
    r"MINI\s*BAR", r"MINIBAR", r"ROOM\s*FRIDGE", r"BEDROOM\s*SERIES",
    r"REFRIGERATOR", r"FRIDGE",
    # door / tub structure
    r"SINGLE\s*DOOR", r"DOUBLE\s*DOOR", r"TRIPLE\s*DOOR", r"FOUR\s*DOOR",
    r"FRENCH\s*DOOR", r"SIDE\s*BY\s*SIDE", r"SINGLE\s*TUB", r"TWIN\s*TUB",
    # operation mode  <-- the RC-1 fix
    r"FULLY\s*[-\s]?\s*AUTOMATIC", r"SEMI\s*[-\s]?\s*AUTOMATIC", r"AUTOMATIC",
    # technology / marketing descriptors
    r"INVERTER", r"NORMAL", r"SERIES", r"DIGITAL", r"GLASS\s+DOOR", r"CLEAR\s+LID",
    r"OPAQUE(?:\s+LID)?", r"NO[\s\-]*FROST", r"CVT", r"SMART", r"WIFI", r"WI-FI",
    r"IOT", r"4K", r"8K", r"FHD", r"UHD", r"HD", r"QLED", r"OLED", r"GOOGLE\s*TV",
    r"ANDROID\s*TV", r"GAS\+ELECTRIC", r"BUILT-IN", r"FIX(?:ED)?\s*SPEED",
    r"HEATING", r"SOLO", r"GRILL", r"IN\s+GRILL", r"BEZEL\s*LESS", r"FRAMELESS",
    # numeric + unit
    r"\d+(?:\.\d+)?[\s\-_]*(?:(?:TON|ΤΟN|KG|GM|LTR|LITRE|LITRES?|LITERS?|L|SETS?|"
    r"FEET|FT|CU\s*FT|CU\.FT|CFT|CU|INCH(?:ES)?|MM|CM)\b|[\"'])",
)

CATEGORY_PATTERNS = re.compile(
    "|".join(rf"\b(?:{p})\b" for p in _CATEGORY_PHRASES), re.IGNORECASE
)

# Every noun inside the category phrases ("WATER DISPENSER" -> WATER, DISPENSER):
# these can never be a colour shade modifier ("Dispenser Purple" is not a shade).
_CATEGORY_WORDS: frozenset[str] = frozenset(
    w for p in _CATEGORY_PHRASES for w in re.findall(r"[A-Za-z]+", p)
)

# --- Merchant / marketplace noise --------------------------------------------
MERCHANT_TRACKING_CODE_RE = re.compile(
    r"\s*\((?:ISPK|SNS|SKU|ID|NS|UE)[-_]?[A-Za-z0-9]+\)\s*"
    r"|\b(?:ISPK|SNS|SKU|ID|NS|UE)[-_]?[A-Za-z0-9]+\b",
    re.IGNORECASE,
)

MARKETPLACE_NOISE_RE = re.compile(
    r"\b(?:ON\s+INSTALLMENT|INSTALLMENT|0%\s*MARKUP|MARKUP|INTEREST|DOWN\s*PAYMENT|EMI"
    r"|CASH\s+ON\s+DELIVERY|COD)\b"
    r"|\b(?:UPTO\s+\d+\s*MONTHS?|\d+\s*MONTHS?|UPTO|MONTHLY|PER\s+MONTH)\b"
    r"|\b(?:FREE\s+(?:HOME\s+)?DELIVERY|FAST\s+DELIVERY|DELIVERY|SHIPPING|EXPRESS"
    r"|FREE\s+INSTALLATION)\b"
    r"|\b(?:OFFICIAL\s+WARRANTY|BRAND\s+WARRANTY|COMPANY\s+WARRANTY|WARRANTY\s+CARD"
    r"|WARRANTY|\d+\s*YEARS?\s+WARRANTY)\b"
    r"|\b(?:SALE|DISCOUNT|DEAL|OFFER|PROMO|PROMOTION|RAMADAN\s+OFFER|EID\s+OFFER"
    r"|SUPER\s+SALE)\b"
    r"|\b(?:ORIGINAL|AUTHENTIC|GENUINE|BRAND\s+NEW|SEALED\s+PACK|SEALED|BOX\s+PACK"
    r"|100%\s*ORIG(?:I)?NAL)\b"
    r"|\b(?:SPECIAL\s+GIFT|SURPRISE\s+GIFT|FREE\s+GIFT|GIFT\s+PACK|GIFT|BEST\s+PRICE)\b"
    r"|\b(?:QUANTUM\s+DOT|QUANTUM|TECHNOLOGY)\b"
    r"|\b(?:ELECTROEASE|HOMECART|METRO|HYPERSTAR|ALFAMALL|FAYSAL\s*BANK|QISTBAZAAR"
    r"|ESBUY|TELEMART|YAYVO)\b"
    r"|\b(?:HEAT\s*(?:&|AND|/)\s*COOL|H\s*&\s*C|COOLING\s*ONLY|COOL\s*ONLY)\b"
    r"|\b(?:INVERTER\s*AC|DC\s*INVERTER|FIX(?:ED)?\s*SPEED|NON[\s\-]*INVERTER)\b"
    r"|\b(?:AAA\+|AA\+|A\+{1,3}|AAA|AA)\b"
    r"|\b(?:FOR\s+[A-Za-z]+\s+ONLY)\b"
    rf"|{MERCHANT_TRACKING_CODE_RE.pattern}",
    re.IGNORECASE,
)

# --- Structural regexes compiled once ----------------------------------------
SAFEGUARD_PATTERN = re.compile(
    r"\b(?:W/M|W/D|D/F|A/C|H/C|H&C|W/O)\b"
    r"|\bHeat\s*/\s*Cool\b"
    r"|\b\d+/\d+\s*(?:\"|(?:inch|mm)\b)"
    r"|\b\d+W/\d+D\b"
    r"|[A-Za-z0-9\-]+/(?:DC|AC)\b"
    r"|[A-Za-z0-9\-]+/T3[A-Za-z0-9\-]*\b"
    r"|[A-Za-z0-9\-]+/KB[-]?\d+"
    r"|[A-Z]{2,}-\d+/\d{2}\b",
    re.IGNORECASE,
)

TAG_PATTERN = re.compile(r"[-_\s]*(?:T3|AAA|AA\+|AA|PRO|ULTRA|PLUS)+$", re.IGNORECASE)

# Unit suffix shared by every "is this a spec?" predicate (was duplicated 3x).
_UNIT_SUFFIX = (
    r"FEET|FT|INCH|MM|CM|KG|GM|LTR|LITRE|LITRES?|LITERS?|L|SETS?|TON|WATTS?|W|V|HZ|\"|'"
)
_UNIT_TOKEN_RE = re.compile(
    rf"^\d+(?:\.\d+)?(?:[-_ ]?(?:{_UNIT_SUFFIX}))?$", re.IGNORECASE
)
_STRICT_UNIT_TOKEN_RE = re.compile(
    rf"^\d+(?:\.\d+)?(?:[-_]?(?:{_UNIT_SUFFIX}))$", re.IGNORECASE
)

# --- AC capacity code -> tonnage (industry BTU/1000 coding) -------------------
UNIVERSAL_CAPACITY_TO_TONNAGE: dict[str, str] = {
    "09": "0.75", "9": "0.75", "12": "1", "18": "1.5", "24": "2",
    "28": "2.5", "30": "2.5", "36": "3", "48": "4",
}
# Dawlance uses proprietary cooling codes.
DAWLANCE_CAPACITY_TO_TONNAGE: dict[str, str] = {
    "10": "0.75", "15": "1", "20": "1.25", "30": "1.5", "45": "2",
}
_CAPACITY_TO_TONNAGE: dict[str, str] = DAWLANCE_CAPACITY_TO_TONNAGE  # back-compat alias
BRAND_CAPACITY_SYSTEMS: dict[str, dict[str, str]] = {"DAW": DAWLANCE_CAPACITY_TO_TONNAGE}

# Derived once: every token that is a known capacity code anywhere.
ALL_CAPACITY_CODES: frozenset[str] = frozenset(UNIVERSAL_CAPACITY_TO_TONNAGE).union(
    *(frozenset(m) for m in BRAND_CAPACITY_SYSTEMS.values())
)

# Derived once: every word that is part of some colour alias.
ALL_COLOR_WORDS: set[str] = {
    word.upper()
    for aliases in COLOR_FAMILIES.values()
    for alias in aliases
    for word in alias.split()
    if word.upper() not in {"CLASSIC", "STEEL", "WOOD", "S.S"}
}


# =============================================================================
# 2. TEXT NORMALISATION
# =============================================================================


@dataclass(frozen=True, slots=True)
class _Masked:
    """Text with safeguarded compounds swapped for placeholders, plus the originals."""

    text: str
    safeguards: tuple[str, ...]

    def restore(self, text: str) -> str:
        for idx, orig in enumerate(self.safeguards):
            text = text.replace(f"__SAFEGUARD_{idx}__", orig)
        return text


def _mask_safeguards(text: str) -> _Masked:
    """Hide compounds that must survive slash expansion untouched (W/M, 1/2", Heat/Cool)."""
    found: list[str] = []

    def swap(m: re.Match[str]) -> str:
        found.append(m.group(0))
        return f"__SAFEGUARD_{len(found) - 1}__"

    return _Masked(SAFEGUARD_PATTERN.sub(swap, text), tuple(found))


def normalize_screen_units(text: str) -> str:
    """Canonicalise screen-size notation: 32" / 32-inch / 32 Inches -> '32 INCH'.

    Fractions such as 1/2" or 12/16" (pipe sizes) are left untouched.
    """
    t = re.sub(
        r"(?<![\d./])(\d{2,3})\s*-?\s*(?:INCHES|INCH)\b", r"\1 INCH", text, flags=re.IGNORECASE
    )
    return re.sub(r"(?<![\d./])(\d{2,3})\s*(?:\"|\u201d|\u2033)", r"\1 INCH", t)


_TECH_SLASH_SUBS: tuple[tuple[str, str], ...] = (
    (r"\b([A-Za-z0-9]+)/Z\b", r"\1Z"),          # 24 HD/Z   -> 24 HDZ
    (r"\b([A-Za-z0-9]+)/(DC|AC)\b", r"\1-\2"),  # 18HE/DC   -> 18HE-DC
    (r"\bH\s*&\s*C\b", "Heat and Cool"),
    (r"\bH/C\b", "Heat and Cool"),
    (r"\bW/M\b", "Washing Machine"),
    (r"\bA/C\b", "AC"),
    (r"\bWI[\s\-]+FI\b", "WIFI"),
)


def normalize_technical_slashes(text: str) -> str:
    """Normalise technical compound codes (/DC, /AC, /Z) and screen units."""
    t = text
    for pattern, repl in _TECH_SLASH_SUBS:
        t = re.sub(pattern, repl, t, flags=re.IGNORECASE)
    return normalize_screen_units(t)


def clean_marketplace_noise(text: str) -> str:
    """Strip e-commerce noise: seller signatures, promos, payment terms, HVAC tags."""
    t = text.strip().translate(_HOMOGLYPHS)
    # Every "|" segment after the first is marketing prose ("… WFL | Powerful
    # Washing | Built-in Buzzer"); long dashes open the same kind of trailing blurb.
    t = re.sub(r"\s*(?:[|–—].*)+$", "", t)
    t = re.sub(r"\s*(?:[-|/]|--)\s*(?:By\s+|Official\s+)?[A-Z][A-Za-z0-9\s.]{2,}$", "", t)
    return MARKETPLACE_NOISE_RE.sub(" ", t).strip()


def strip_brand_prefix(text: str, brand: str) -> str:
    """Remove a leading brand name (or its 3-letter abbreviation) repeatedly."""
    clean = text.strip()
    if not brand:
        return clean
    abbr = re.escape(brand[:3]) if len(brand) >= 4 else "---"
    pattern = rf"^(?:{re.escape(brand)}|{abbr})[\s\-_,:]*"
    while re.match(pattern, clean, flags=re.IGNORECASE):
        clean = re.sub(pattern, "", clean, count=1, flags=re.IGNORECASE).strip()
    return clean


# ``12 SVN-AI-CO-31S`` -> ``12SVN-AI-CO-31S`` (capacity glued to the alpha stem).
_CAPACITY_STEM_ALPHABET = "|".join(
    sorted(UNIVERSAL_CAPACITY_TO_TONNAGE, key=len, reverse=True)
)
_CAPACITY_STEM_RE = re.compile(
    rf"\b({_CAPACITY_STEM_ALPHABET})\s+([A-Za-z]{{2,}}[-_A-Za-z0-9]*(?:\d+|-)[-_A-Za-z0-9]*)\b"
)


def join_capacity_stems(text: str) -> str:
    """Glue a spaced capacity code onto the following alphanumeric model stem."""
    return _CAPACITY_STEM_RE.sub(r"\1\2", text)


# Confusable homoglyphs actually present in the input catalogs.  Greek capitals
# reach the sheets through keyboard-layout slips ("1.5 ΤΟΝ" for "1.5 TON"), which
# silently turned a capacity unit into an unmatchable series name.  Character-level
# folding only -- no product vocabulary is involved.
_HOMOGLYPHS = str.maketrans({
    "\u0391": "A", "\u0392": "B", "\u0395": "E", "\u0396": "Z", "\u0397": "H",
    "\u0399": "I", "\u039A": "K", "\u039C": "M", "\u039D": "N", "\u039F": "O",
    "\u03A1": "P", "\u03A4": "T", "\u03A5": "Y", "\u03A7": "X",
})


def _squash(text: str) -> str:
    """Alphanumeric-only uppercase form used for containment checks."""
    return re.sub(r"[^A-Z0-9]", "", text.upper())


def detect_brand(text: str, brand: str = "") -> str:
    """Resolve the effective brand: catalog metadata wins, else the leading word."""
    first = text.split()[0] if text.split() else ""
    return (brand or (first if first and not re.search(r"\d", first) else "")).strip()


# =============================================================================
# 3. TOKEN PREDICATES
# =============================================================================


def is_color_token(token: str) -> bool:
    """True if the token is a normalized colour word or a single-letter colour code."""
    clean = token.strip("-_., \"'").upper()
    return clean in ALL_COLOR_WORDS or clean in COLOR_SUFFIX_MAP


def normalize_color(title: str, anchor: str = "") -> tuple[str | None, str | None]:
    """Map a title onto one of the 9 canonical colour families.

    Inviolability rule: letters *inside* an alphanumeric anchor (120-826S6, 276EBS)
    are never re-read as colour names -- the anchor is blanked out first.
    """
    haystack = title
    if anchor:
        haystack = re.sub(rf"\b{re.escape(anchor)}\b", " ", title, flags=re.IGNORECASE)

    for family, aliases in COLOR_FAMILIES.items():
        for alias in aliases:
            if re.search(rf"\b{re.escape(alias)}\b", haystack, re.IGNORECASE):
                return family, alias

    # Single-letter variant codes resolve through the ONE sanctioned colour
    # vocabulary (COLOR_SUFFIX_MAP) so a code and its full word agree: ``B`` ==
    # Black, ``C`` == Champagne, and ``C`` != ``S``.  One table, one code path for
    # both glued and standalone letters -- no per-product logic.
    if anchor:  # standalone single-letter code immediately after the anchor
        m = re.search(rf"\b{re.escape(anchor)}\s*[-_]?\s*([A-Za-z])\b", title, re.IGNORECASE)
        if m:
            letter = m.group(1).upper()
            if letter not in GENUINE_SUB_SERIES_TOKENS and COLOR_SUFFIX_MAP.get(letter):
                return COLOR_SUFFIX_MAP[letter], letter
    if anchor:  # single-letter code glued to the anchor's digit run (18AITH21W -> W)
        m = re.search(r"\d([A-Za-z])$", anchor)
        if m and COLOR_SUFFIX_MAP.get(m.group(1).upper()):
            return COLOR_SUFFIX_MAP[m.group(1).upper()], m.group(1).upper()
    return None, None


def get_all_color_families(text: str) -> set[str]:
    """Every canonical colour family present in a model code or title."""
    families: set[str] = set()
    for family, aliases in COLOR_FAMILIES.items():
        if any(
            re.search(rf"\b{re.escape(alias)}\b", text, re.IGNORECASE) for alias in aliases
        ):
            families.add(family)
    for token in text.split():
        m = re.search(r"\d+[A-Za-z]+?\d+([WBSGDRP])$", token.strip("-_., \"'"), re.IGNORECASE)
        if m and COLOR_SUFFIX_MAP.get(m.group(1).upper()):
            families.add(COLOR_SUFFIX_MAP[m.group(1).upper()])
    return families


_SHADE_STOP: frozenset[str] = frozenset(
    {"WITH", "NEW", "STYLE", "EDITION", "COLOR", "COLOUR", "FINISH", "TYPE", "SHADE", "MODEL"}
)


def _color_shade(title: str, anchor: str = "") -> str | None:
    """Two-layer colour: the shade modifier attached to the matched base colour.

    ``Smoke Purple`` -> base family Purple + shade ``SMOKE``; ``Ruby Red`` ->
    Red + ``RUBY``.  Structural rule, zero per-product vocabulary: the word
    immediately before the matched colour alias, provided it is not itself a
    colour, a category noun (Dispenser/Glass/Door), a spec token, or noise.
    A shade that the listing omits is an *omission* (BASE + notice), while two
    different declared shades (Diamond Red vs Ruby Red) collide (REJECT).
    """
    family, alias = normalize_color(title, anchor=anchor)
    if not family or not alias or len(alias) < 3:
        return None
    # A multi-word alias ("MILKY WHITE") is itself shade + base: decompose it.
    parts = alias.split()
    if len(parts) >= 2 and parts[-1].upper() in ALL_COLOR_WORDS:
        return " ".join(parts[:-1]).upper()
    m = re.search(rf"\b([A-Za-z]{{3,12}})\s+{re.escape(alias)}\b", title, re.IGNORECASE)
    if not m:
        return None
    word = m.group(1).upper()
    # A colour word in front of another colour word IS a shade modifier
    # ("Ruby Red", "Pearl White"); category nouns / specs / noise are not.
    if (
        word in _SHADE_STOP
        or word in _CATEGORY_WORDS
        or word in NON_SKU_TOKENS
        or word in _NAME_STOP
        or is_dimension_or_spec_token(word)
    ):
        return None
    return word


_SPEC_SHAPES: tuple[tuple[re.Pattern[str], bool], ...] = (
    (re.compile(r"^T\d+$", re.IGNORECASE), True),              # 1T, 2T tonnages
    (re.compile(r"^(?:19|20)\d{2}$"), True),                   # model years
    (re.compile(r"^[48]K$", re.IGNORECASE), True),             # 4K / 8K
    (re.compile(r"^\d{1,2}K$", re.IGNORECASE), True),          # 2K 4K 8K
    (re.compile(r"^(?:480|576|720|1080|1440|2160)[PI]$", re.IGNORECASE), True),
    (re.compile(r"^\d+IN\d+$", re.IGNORECASE), True),          # 3IN1, 2IN1
)


def is_dimension_or_spec_token(token: str) -> bool:
    """True for physical dimensions / capacities / feature counts (not model codes).

    Standalone pure numbers of >= 3 digits (1088, 9270, 330) *are* valid model codes.
    """
    clean = token.strip("-_., \"'")
    if not clean or clean.upper() in NON_SKU_TOKENS:
        return True
    for pattern, _ in _SPEC_SHAPES:
        if pattern.match(clean):
            return True
    if _UNIT_TOKEN_RE.match(clean):
        return len(clean) <= 2 if clean.isdigit() else True
    return False


# Short codes that are variant tags rather than colours / series / units.
_VARIANT_ALWAYS: frozenset[str] = frozenset({"INOX"})
_VARIANT_NEVER: frozenset[str] = frozenset({"WB", "GB"})


def is_sku_variant_tag(token: str) -> bool:
    """Dynamically classify a token as an SKU variant tag (PL, FLT, ES, T3, ES8, S6).

    Structural rule, zero hardcoded colour or series lists:
    * pure numbers / decimals  -> capacity, not a tag
    * number + unit            -> spec, not a tag
    * genuine sub-series word  -> series, not a tag
    * colour word              -> colour, not a tag
    * digits + letters, <= 2 digits, <= 4 chars -> tag (T3, S6, ES8, 11S)
    * 2-4 pure letters         -> tag (ES, FLT, IFGA, CHZP)
    """
    clean = token.strip("-_., \"'")
    if not clean or clean.upper() in NON_SKU_TOKENS:
        return False
    if MERCHANT_TRACKING_CODE_RE.search(clean):
        return False
    upper = clean.upper()
    if upper in _VARIANT_NEVER:
        return False
    if upper in _VARIANT_ALWAYS:
        return True
    if is_color_token(clean) or upper in GENUINE_SUB_SERIES_TOKENS:
        return False
    if re.match(r"^\d+(?:\.\d+)?$", clean) or _STRICT_UNIT_TOKEN_RE.match(clean):
        return False
    if re.match(r"^\d+IN\d+$", clean, re.IGNORECASE):
        return False
    if re.search(r"\d", clean):
        return (
            bool(re.search(r"[A-Za-z]", clean))
            and len(re.findall(r"\d", clean)) <= 2
            and len(clean) <= 4
        )
    return 2 <= len(clean) <= 4 and clean.isalpha()


def extract_tag(s: str) -> tuple[str, str]:
    """Split a trailing auxiliary tag (-T3, -ES, AAA, PRO) off a token core."""
    if "-" in s:
        parts = s.split("-")
        if len(parts) > 1 and any(re.search(r"\d", p) for p in parts[:-1]):
            trailing = parts[-1].strip()
            if is_sku_variant_tag(trailing) or trailing.upper() in GENUINE_SUB_SERIES_TOKENS:
                return "-".join(parts[:-1]), f"-{trailing}"
    # Glued tag on a prefix+numeric stem: DWT11467ES -> (DWT11467, -ES)
    m = re.match(r"^([A-Za-z]{2,4}\d{3,})([A-Za-z]{2,4})$", s)
    if m and is_sku_variant_tag(m.group(2)):
        return m.group(1), f"-{m.group(2)}"
    m = TAG_PATTERN.search(s)
    if m:
        return s[: m.start()], m.group(0)
    return s, ""


def split_runs(s: str) -> list[tuple[str, str]]:
    """Split into ordered typed runs: ('D', digits) / ('L', letters) / ('P', punct)."""
    runs: list[tuple[str, str]] = []
    for m in re.finditer(r"([0-9]+)|([A-Za-z]+)|([^0-9A-Za-z\s]+)", s):
        kind, value = next(
            (k, g) for k, g in (("D", m.group(1)), ("L", m.group(2)), ("P", m.group(3))) if g
        )
        runs.append((kind, value))
    return runs


# =============================================================================
# 4. VARIANT / BRANCH EXPANSION
# =============================================================================


@dataclass(frozen=True, slots=True)
class _VariantPart:
    """Structural decomposition of one slash alternative (e.g. ``21B-T3``)."""

    raw: str
    core: str
    digits: str
    middle: str
    letters: str
    tag: str

    @classmethod
    def parse(cls, part: str) -> _VariantPart:
        core, tag = extract_tag(part)
        m_digits = re.match(r"^([0-9]+)", core)
        digits = m_digits.group(1) if m_digits else ""
        remainder = core[len(digits):]
        m_letters = re.search(r"([A-Za-z]+)$", remainder)
        letters = m_letters.group(1) if m_letters else ""
        return cls(part, core, digits, remainder[: len(remainder) - len(letters)], letters, tag)

    def rebuild(self, stem: str, digits: str, letters: str, tag: str) -> str:
        return f"{stem}{digits or self.digits}{self.middle}{letters or self.letters}{tag}"


def _parse_variant_parts(parts: Sequence[str]) -> list[_VariantPart]:
    return [_VariantPart.parse(p) for p in parts]


def _common_tag(parts: Sequence[_VariantPart], trailing_tag: str = "") -> str:
    if trailing_tag:
        return trailing_tag
    return next((p.tag for p in reversed(parts) if p.tag), "")


def _distribute_digits(parts: Sequence[_VariantPart], prefix_digits: str) -> str:
    """Share a leading numeric prefix with the alternatives that lack one."""
    lacks = any(not p.digits and p.letters for p in parts[1:])
    return prefix_digits if (prefix_digits and lacks) else ""


def _distribute_letters(parts: Sequence[_VariantPart], last_letters: str, first_has: bool) -> str:
    lacks = any(not p.letters for p in parts[:-1]) if len(parts) > 1 else False
    return last_letters if (last_letters and (lacks or not first_has)) else ""


def distribute_runs(stem: str, parts: Sequence[str], trailing_tag: str = "") -> list[str]:
    """Distribute shared numeric prefixes / letter suffixes / tags across variants."""
    parsed = _parse_variant_parts(parts)
    tag = _common_tag(parsed, trailing_tag)
    share_digits = _distribute_digits(parsed, parsed[0].digits)
    share_letters = _distribute_letters(parsed, parsed[-1].letters, first_has=True)
    return [
        p.rebuild(stem, share_digits, share_letters, p.tag or tag) for p in parsed
    ]


def expand_slash_word(word: str) -> list[str]:
    """Expand one slash-separated model token by structural run alignment."""
    raw_parts = [p.strip() for p in word.split("/") if p.strip()]
    if len(raw_parts) < 2:
        return [word]

    parsed = _parse_variant_parts(raw_parts)
    lead_runs = split_runs(parsed[0].core)
    sub_runs = split_runs(parsed[1].core)
    sub_types = [t for t, _ in sub_runs]

    # Align the alternative's run sequence against the tail of the leading token.
    split_idx = -1
    if len(lead_runs) >= len(sub_runs) and [t for t, _ in lead_runs[-len(sub_runs):]] == sub_types:
        split_idx = len(lead_runs) - len(sub_runs)
    if split_idx == -1 and sub_types and sub_types[0] == "D":
        want = len(sub_runs[0][1])
        split_idx = next(
            (i for i in range(len(lead_runs) - 1, -1, -1)
             if lead_runs[i][0] == "D" and len(lead_runs[i][1]) == want),
            -1,
        )
    if split_idx == -1 and sub_types == ["L"]:
        split_idx = next(
            (i for i in range(len(lead_runs) - 1, -1, -1) if lead_runs[i][0] == "L"), -1
        )
    if split_idx == -1 and sub_types:
        split_idx = next(
            (i for i in range(len(lead_runs) - 1, -1, -1) if lead_runs[i][0] == sub_types[0]), -1
        )

    if split_idx != -1:
        stem = "".join(v for _, v in lead_runs[:split_idx])
        var0_core = "".join(v for _, v in lead_runs[split_idx:])
    else:
        stem, var0_core = "", parsed[0].core

    tag = _common_tag(parsed)
    m_var0_digits = re.match(r"^([0-9]+)", var0_core)
    prefix_digits = m_var0_digits.group(1) if m_var0_digits else ""
    share_digits = _distribute_digits(parsed, prefix_digits)
    var0_remainder = var0_core[len(prefix_digits):]
    var0_has_letters = bool(re.search(r"([A-Za-z]+)$", var0_remainder))
    share_letters = _distribute_letters(parsed, parsed[-1].letters, first_has=var0_has_letters)

    first = f"{stem}{var0_core}{share_letters if not var0_has_letters else ''}"
    first += parsed[0].tag or tag
    rest = [p.rebuild(stem, share_digits, share_letters, p.tag or tag) for p in parsed[1:]]
    return [first, *rest]


def expand_cartesian_branches(title: str) -> list[str]:
    """Expand slash-separated *alternative models* into independent titles."""
    masked = _mask_safeguards(normalize_technical_slashes(title))
    t = masked.text
    slashes = list(re.finditer(r"(\b[A-Za-z0-9\-_]+)\s*/\s*([A-Za-z0-9\-_]+)", t))

    def is_real(m: re.Match[str]) -> bool:
        return (
            len(m.group(1)) >= 2
            and len(m.group(2)) >= 2
            and not m.group(1).startswith("__SAFEGUARD_")
            and not m.group(2).startswith("__SAFEGUARD_")
        )

    branches: list[str]
    # A run of *adjacent* slashes is a single alternative list ("GS-24PITH15/16/17/18G"),
    # not two independent variant axes.  Pairing them off as a cartesian product
    # invents model codes that do not exist ("GS-24PITH15/17", "16/18G-T3").
    multi = re.search(
        r"\b[A-Za-z0-9\-_]+(?:\s*/\s*[A-Za-z0-9\-_]+){2,}", t
    )
    if multi and not multi.group(0).startswith("__SAFEGUARD_"):
        head, tail = t[: multi.start()], t[multi.end():]
        branches = [
            (head + w + tail).strip()
            for w in dict.fromkeys(expand_slash_word(multi.group(0)))
        ]
    elif len(slashes) >= 2 and all(is_real(s) for s in slashes[:2]):
        s1, s2 = slashes[0], slashes[1]
        mid = t[s1.end(): s2.start()]
        branches = [
            (t[: s1.start()] + s1.group(i) + mid + s2.group(i) + t[s2.end():]).strip()
            for i in (1, 2)
        ]
    elif len(slashes) == 1 and is_real(slashes[0]):
        m = slashes[0]
        left, right = m.group(1).strip(), m.group(2).strip()
        if len(left) >= 3 and len(right) >= 3:
            head, tail = t[: m.start()], t[m.end():]
            branches = [(head + left + tail).strip(), (head + right + tail).strip()]
            if "-" in left:
                pfx, stem_left = left.rsplit("-", 1)
                branches += [
                    (head + stem_left + tail).strip(),
                    (head + f"{pfx}-{right}" + tail).strip(),
                ]
            branches = list(dict.fromkeys(branches))
        else:
            branches = [t.strip()]
    else:
        branches = [t.strip()]

    return [masked.restore(b) for b in branches]


def _repl_savein_svn(full: bool) -> Callable[[re.Match[str]], str]:
    """Build the SaveIN <-> SVN equivalence rewriter (one implementation, two modes)."""

    def repl(m: re.Match[str]) -> str:
        num, tag = m.group(1), m.group(2)
        alt = "SVN" if "SAVE" in tag.upper() else "SaveIN"
        if full:
            rest = m.group(3)
            return f"{m.group(0)} {num}{alt}{rest} TAC-{num}SVN{rest}"
        return f"{m.group(0)} {num}{alt} TAC-{num}SVN"

    return repl


_SAVEIN_FULL_RE = re.compile(
    rf"\b(?:TAC[-_]?)?({_CAPACITY_STEM_ALPHABET})[-_]?(SaveIN|SVN)([-_][A-Za-z0-9\-_]+)\b",
    re.IGNORECASE,
)
_SAVEIN_BARE_RE = re.compile(
    rf"\b({_CAPACITY_STEM_ALPHABET})\s*[-_]?\s*(SaveIN|SVN)\b(?![A-Za-z0-9\-_])",
    re.IGNORECASE,
)
_SLASH_TIGHTEN_RE = re.compile(r"([A-Za-z0-9\-_]+)\s*[/,]\s*([A-Za-z0-9\-_]+)")
_PAREN_VARIANT_RE = re.compile(
    r"\b([A-Za-z0-9\-_]+)\s*[\(\[]\s*([A-Za-z0-9\-_]+(?:\s*[/,]\s*[A-Za-z0-9\-_]+)+)\s*[\)\]]",
    re.IGNORECASE,
)


def expand_multivariant_titles(title: str) -> str:
    """Expand slash / comma / parenthesised variant tokens into distinct model tokens.

    Handles compound hyphenated suffixes, colour alternates, multi-generation series,
    parenthesised variants and multi-model lists with one alignment algorithm.
    """
    masked = _mask_safeguards(title)
    t = masked.text

    def paren_repl(m: re.Match[str]) -> str:
        parts = [p.strip() for p in re.split(r"\s*[/,]\s*", m.group(2)) if p.strip()]
        if len(parts) < 2:
            return m.group(0)
        return " ".join(distribute_runs(m.group(1).rstrip("-_ "), parts))

    t = _PAREN_VARIANT_RE.sub(paren_repl, t)

    # Universal finish synonyms so 'Glass Door'/'Stainless Steel' also yield GD/INOX.
    t = re.sub(r"\bGLASS\s+DOOR\b", "GLASS DOOR GD", t, flags=re.IGNORECASE)
    t = re.sub(r"\bSTAINLESS\s+STEEL\b", "STAINLESS STEEL INOX", t, flags=re.IGNORECASE)

    t = join_capacity_stems(t)
    t = _SAVEIN_FULL_RE.sub(_repl_savein_svn(full=True), t)
    t = _SAVEIN_BARE_RE.sub(_repl_savein_svn(full=False), t)

    t = _SLASH_TIGHTEN_RE.sub(r"\1/\2", t)
    t = re.sub(r"([A-Za-z0-9]+)\s+-\s+([A-Za-z0-9]+/[A-Za-z0-9]+)", r"\1-\2", t)

    words = t.split()
    out: list[str] = []
    i = 0
    while i < len(words):
        w = words[i]
        if "/" in w and not w.startswith("__SAFEGUARD_"):
            expanded = expand_slash_word(w)
            if i + 1 < len(words) and is_sku_variant_tag(words[i + 1]):
                expanded = [f"{x} {words[i + 1]}" for x in expanded]
                i += 1
            out.extend(expanded)
        else:
            out.append(w)
        i += 1

    return masked.restore(" ".join(out))


# =============================================================================
# 5. CAPACITY / TONNAGE RESOLUTION
# =============================================================================


def _invert_capacity_map(cap_map: dict[str, str]) -> dict[str, set[str]]:
    inv: dict[str, set[str]] = {}
    for code, ton in cap_map.items():
        inv.setdefault(ton, set()).add(code)
        if "." not in ton:
            inv.setdefault(f"{ton}.0", set()).add(code)
    return inv


UNIVERSAL_TONNAGE_TO_CODES: dict[str, set[str]] = _invert_capacity_map(
    UNIVERSAL_CAPACITY_TO_TONNAGE
)
DAWLANCE_TONNAGE_TO_CODES: dict[str, set[str]] = _invert_capacity_map(
    DAWLANCE_CAPACITY_TO_TONNAGE
)


def get_capacity_map(brand: str = "") -> dict[str, str]:
    """Resolve the capacity->tonnage table for a brand, defaulting to Universal."""
    b = brand.strip().upper()
    for prefix, cap_map in BRAND_CAPACITY_SYSTEMS.items():
        if b.startswith(prefix):
            return cap_map
    return UNIVERSAL_CAPACITY_TO_TONNAGE


def get_tonnage_map(brand: str = "") -> dict[str, set[str]]:
    return _invert_capacity_map(get_capacity_map(brand))


def get_capacity_tonnage(code: str, brand: str = "") -> str | None:
    """Tonnage for an AC capacity code, brand-aware (exclusive codes win when unknown)."""
    clean = code.strip().upper()
    if brand:
        return get_capacity_map(brand).get(clean)
    for cap_map in BRAND_CAPACITY_SYSTEMS.values():
        if clean in cap_map and clean not in UNIVERSAL_CAPACITY_TO_TONNAGE:
            return cap_map.get(clean)
    return UNIVERSAL_CAPACITY_TO_TONNAGE.get(clean)


def tonnage_matches_title(tonnage: str, title_upper: str) -> bool:
    """Does the title state this tonnage (1.5 Ton / 1 Ton / 1.0 Ton / 0.75 Ton)?"""
    if "." not in tonnage:
        num = rf"(?:{re.escape(tonnage)}(?:\.0)?)"
    elif tonnage.startswith("0."):
        num = rf"(?:0?{re.escape(tonnage[1:])})"
    else:
        num = rf"(?:{re.escape(tonnage)})"
    return bool(re.search(rf"\b{num}\s*(?:TON|ΤΟN)\b", title_upper))


def reverse_tonnage_matches(kw: str, title_words: set[str], brand: str = "") -> bool:
    """Target states a tonnage; does the title carry an equivalent capacity code?"""
    codes = get_tonnage_map(brand).get(kw)
    return bool(codes and codes.intersection(title_words))


# =============================================================================
# 6. MODEL EXTRACTION
# =============================================================================

_SKU_PREFIX_RE_CACHE: dict[str, re.Pattern[str]] = {}


def detect_sku_prefix(text: str, brand: str = "") -> tuple[str, str]:
    """Find the 2-4 letter SKU prefix glued to the first numeric stem.

    Returns ``(prefix_upper, stem_num)``.  This is the single generic prefix rule
    mandated by AGENTS.md; extraction, slots and search patterns all share it.
    """
    m_num = re.search(r"\d+", text)
    if not m_num:
        return "", ""
    stem = m_num.group(0)
    m = re.search(rf"\b([A-Za-z]{{2,4}})[- ]?{re.escape(stem)}", text)
    if not m:
        return "", stem
    prefix = m.group(1).upper()
    if prefix.lower() == brand.strip().lower() or prefix in NON_SKU_TOKENS:
        return "", stem
    return prefix, stem


def _merge_prefix_number_tokens(tokens: list[str]) -> list[str]:
    """Glue a letter prefix onto a short capacity code that follows it (``DW-MD 4``).

    Deliberately limited to 1-2 digit capacity codes: gluing a prefix onto a long
    numeric stem would also rewrite ``DMB 4467 SD`` into ``DMB-4467SD`` and destroy
    the minibar SKU family.  Long stems keep their prefix via substring containment
    in the referee instead.
    """
    merged: list[str] = []
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        nxt = tokens[i + 1] if i + 1 < len(tokens) else None
        if (
            nxt is not None
            and re.match(r"^[A-Za-z]{2,4}(?:-[A-Za-z]{2,4})?$", tok)
            and tok.upper() not in GENUINE_SUB_SERIES_TOKENS
            and tok.upper() not in NON_SKU_TOKENS
            and re.match(r"^\d{1,2}$", nxt)
        ):
            after = tokens[i + 2] if i + 2 < len(tokens) else None
            if (
                after is not None
                and re.match(r"^[A-Za-z]{1,3}$", after)
                and after.upper() not in NON_SKU_TOKENS
                and not is_color_token(after)
            ):
                merged.append(f"{tok}-{nxt}{after}")
                i += 3
                continue
            merged.append(f"{tok}-{nxt}")
            i += 2
            continue
        merged.append(tok)
        i += 1
    return merged


_NAME_STOP: frozenset[str] = frozenset(
    {"INVERTER", "INV", "SERIES", "NORMAL", "COOL", "ONLY", "+", "(", ")", "[", "]"}
)


def extract_search_query_and_model(full_name: str, brand: str = "") -> tuple[str, str]:
    """Extract ``(clean_search_query, raw_model_code)`` from a catalog product name.

    Brand-agnostic and DRY: no brand lists, no colour lists, no static prefix sets.
    """
    clean = full_name.replace("—", " ").replace("–", " ").replace("|", " ").strip()
    detected_brand = detect_brand(clean, brand)
    clean = strip_brand_prefix(clean, detected_brand)
    clean = normalize_technical_slashes(clean)
    clean = join_capacity_stems(clean)

    # Descriptive series + capacity with no trailing model code ("Magna 1.5 Ton").
    m_desc = re.search(
        r"^(.*?)\s+(\d+(?:\.?\d+)?)\s*(?:ton|tonnage|kg|inch|\"|\')"
        r"(?:\s+(?:inverter|fix(?:ed)?\s*speed|ac|split|heat\s*&\s*cool|cool\s*only))*$",
        clean,
        flags=re.IGNORECASE,
    )
    if m_desc and m_desc.group(1).strip().upper() not in {
        "SPLIT", "SPLIT AC", "INVERTER", "AC", "AUTO", "AWM"
    }:
        series_name, cap_val = m_desc.group(1).strip(), m_desc.group(2).strip()
        model = f"{series_name} {cap_val}"
        query = f"{detected_brand} {model}".strip() if detected_brand else model
        return query, model

    # TV pattern: 32" D2 -> model "32 D2" (unless a real SKU follows downstream).
    m_tv = re.search(
        r"\b(\d{2})\s*-?\s*(?:\"|inches|inch|\')\s+([A-Za-z0-9][A-Za-z0-9\-_]*)\b",
        clean,
        flags=re.IGNORECASE,
    )
    if m_tv and m_tv.group(2).upper() not in NON_SKU_TOKENS:
        cand_tv = m_tv.group(2)
        has_downstream_sku = bool(
            re.search(
                r"\b(?!\d{2}\s*(?:inch|\"|\'))[A-Za-z0-9\-_]*\d+[A-Za-z0-9\-_]*\b",
                clean[m_tv.end():],
                flags=re.IGNORECASE,
            )
        )
        if re.search(r"\d", cand_tv) or not has_downstream_sku:
            model = f"{m_tv.group(1)} {cand_tv}"
            query = f"{detected_brand} {model}".strip() if detected_brand else model
            return query, model

    clean = CATEGORY_PATTERNS.sub(" ", clean).strip()
    tokens = _merge_prefix_number_tokens(clean.split())

    # Capacity-code + series shape: "24 HDZ", "18 HE-DC", "32 D2".
    if len(tokens) >= 2 and tokens[0].isdigit() and len(tokens[0]) <= 2:
        second = tokens[1].strip("-.,_ \"'")
        if re.search(r"^[A-Za-z0-9\-_]+$", second) and second.upper() not in NON_SKU_TOKENS:
            rest = [t.strip("-.,_ \"'") for t in tokens[2:] if is_sku_variant_tag(t)]
            raw_model = f"{tokens[0]} {second}" + (f" {' '.join(rest)}" if rest else "")
            query = f"{detected_brand} {second} {tokens[0]}".strip() if detected_brand else (
                f"{second} {tokens[0]}"
            )
            return query, raw_model

    model_tokens: list[str] = []
    for t in tokens:
        t_clean = t.strip("-.,_ \"'")
        if not t_clean or t_clean.upper() in NON_SKU_TOKENS:
            continue
        if not model_tokens:
            if (
                len(t_clean) >= 3
                and re.search(r"\d", t_clean)
                and not is_dimension_or_spec_token(t_clean)
                and re.match(r"^[A-Za-z0-9\-_/()]+$", t_clean)
            ):
                model_tokens.append(t_clean)
        elif is_sku_variant_tag(t_clean) or (
            model_tokens[0].isdigit() and is_color_token(t_clean)
        ):
            if t_clean.upper() not in [p.upper() for p in model_tokens[0].split("-")]:
                model_tokens.append(t_clean)
        else:
            break

    if model_tokens:
        raw_model = " ".join(model_tokens)
        first = model_tokens[0]
        # Drop a brand-initial form-factor wrapper only when series letters follow the
        # digits (Gree GS-12AITH -> 12AITH).  Genuine prefixes (WF-5254) are kept.
        if detected_brand and re.search(r"\d+[A-Za-z]", first):
            first = re.sub(
                rf"^{re.escape(detected_brand[0])}[A-Za-z][-_]?(?=\d)",
                "",
                first,
                flags=re.IGNORECASE,
            )
        base = first.split("/")[0].strip() if "/" in first else first
        parts = base.split("-")
        search_token = parts[0] if parts and len(parts[0]) >= 5 else base
        if re.search(r"Save[-_ ]?IN", search_token, re.IGNORECASE):
            search_token = re.sub(r"Save[-_ ]?IN", "SVN", search_token, flags=re.IGNORECASE)
        return search_token, raw_model

    return _extract_keyword_model(clean, full_name, detected_brand)


def _extract_keyword_model(clean: str, full_name: str, brand: str) -> tuple[str, str]:
    """Name-only fallback: no digit-bearing model token was found."""
    remaining = re.sub(r"[()]", " ", CATEGORY_PATTERNS.sub(" ", clean).strip())
    significant: list[str] = []
    capacity = ""
    for t in remaining.split():
        t_clean = t.strip("-.,_ \"'+")
        if not t_clean:
            continue
        up = t_clean.upper()
        if up in ALL_CAPACITY_CODES and not capacity:
            capacity = t_clean
            significant.append(t_clean)
        elif up not in _NAME_STOP and up not in NON_SKU_TOKENS:
            significant.append(t_clean)

    if not capacity:
        m_ton = re.search(r"\b(\d+(?:\.\d+)?)\s*(?:TON|ΤΟN)\b", full_name, re.IGNORECASE)
        if m_ton:
            codes = get_tonnage_map(brand).get(m_ton.group(1))
            if codes:
                capacity = sorted(codes)[0]
                significant.append(capacity)

    if not significant:
        # Nothing survived stripping (e.g. "DAWLANCE 9KG AUTOMATIC TOP LOAD WASHING
        # MACHINE"): never hand back an empty model -- fall back to the cleaned name.
        parts = clean.split()
        fallback = parts[-1] if parts else full_name.strip()
        return fallback, (clean or full_name.strip())

    query_parts = [brand] if brand else []
    series_words = [w for w in significant if w not in (capacity, "/")]
    query_parts.append(series_words[0] if series_words else significant[0])
    if capacity:
        query_parts.append(capacity)
    return " ".join(query_parts), " ".join(significant)


# =============================================================================
# 7. SEARCH PATTERN GENERATION  (ADR-001 tiered waterfall)
# =============================================================================


class _TierBuilder:
    """Ordered, de-duplicating accumulator for the three waterfall tiers."""

    def __init__(self, brand: str) -> None:
        self.brand = brand.strip()
        self.tiers: dict[str, list[str]] = {"tier_1": [], "tier_2": [], "tier_3": []}

    def with_brand(self, text: str) -> str:
        t = text.strip()
        if not self.brand or not t:
            return t or self.brand
        return t if t.lower().startswith(self.brand.lower()) else f"{self.brand} {t}"

    @staticmethod
    def with_prefix(prefix: str, text: str, sep: str = " ") -> str:
        p, t = prefix.strip().upper(), text.strip()
        if not p or not t:
            return t
        return t if t.upper().startswith(p) else f"{p}{sep}{t}"

    def plain(self, tier: str, *texts: str) -> None:
        for text in texts:
            if text.strip():
                self.tiers[tier].append(text.strip())

    def branded(self, tier: str, *texts: str) -> None:
        """Emit only when a brand is known -- mirrors the original `if detected_brand`."""
        if self.brand:
            self.plain(tier, *(self.with_brand(t) for t in texts))

    def result(self) -> dict[str, list[str]]:
        return {
            tier: list(dict.fromkeys(s for s in items if s.strip()))
            for tier, items in self.tiers.items()
        }


_TV_ANCHOR_RE = re.compile(r"^(\d{2})([A-Z]\w{3,})$")
_FRIDGE_ANCHOR_RE = re.compile(r"^(\d{3,})([A-Za-z]+)$")
_COLOR_SUFFIX_ANCHOR_RE = re.compile(r"^(\d+[A-Za-z]+?\d+)[WBSG]$", re.IGNORECASE)


def _generate_single_branch_patterns(canonical_name: str, brand: str = "") -> dict[str, list[str]]:
    """Tiered waterfall queries for one canonical branch (see ADR-001)."""
    clean_name = join_capacity_stems(canonical_name.strip())
    if not clean_name:
        return {"tier_1": [], "tier_2": [], "tier_3": []}

    detected_brand = brand.strip() or clean_name.split()[0]
    _, raw_model = extract_search_query_and_model(clean_name, brand=detected_brand)
    b = _TierBuilder(detected_brand)

    prefix, stem_num = detect_sku_prefix(clean_name, detected_brand)
    tokens = raw_model.split()
    first_token = tokens[0] if tokens else raw_model
    core_stem, aux_tag = extract_tag(first_token)

    tv_match = _TV_ANCHOR_RE.match(first_token)
    is_leading_cap = len(tokens) >= 2 and tokens[0].isdigit() and len(tokens[0]) <= 2
    is_trailing_cap = len(tokens) >= 2 and tokens[-1].isdigit() and len(tokens[-1]) <= 2

    if tv_match:
        screen, series = tv_match.group(1), tv_match.group(2)
        b.plain("tier_1", first_token)
        b.branded("tier_1", first_token)
        b.plain("tier_2", series)
        b.plain("tier_3", f"{screen} {series}")
        b.branded("tier_3", series)
    elif is_leading_cap or is_trailing_cap:
        _series_capacity_patterns(b, tokens, raw_model, is_leading_cap)
    else:
        _standard_model_patterns(
            b,
            clean_name=clean_name,
            raw_model=raw_model,
            bare_stem=core_stem,
            aux_tag=aux_tag,
            prefix=prefix,
            stem_num=stem_num,
        )

    return {
        tier: [q for q in (_sane_query(x) for x in items) if q]
        for tier, items in b.result().items()
    }


def _series_capacity_patterns(
    b: _TierBuilder, tokens: list[str], raw_model: str, is_leading_cap: bool
) -> None:
    """Queries for a ``series + capacity code`` model (MAGNA 30, 15 INFINITY PRO)."""
    cap_code = tokens[0] if is_leading_cap else tokens[-1]
    series_tokens = tokens[1:] if is_leading_cap else tokens[:-1]
    series_clean = " ".join(
        t for t in series_tokens if t.upper() not in NON_SKU_TOKENS and t != "+"
    ).strip()
    options = (
        [s.strip() for s in series_clean.split("/") if s.strip()]
        if "/" in series_clean
        else ([series_clean] if series_clean else [" ".join(series_tokens)])
    )
    for opt in options:
        b.plain("tier_1", f"{opt} {cap_code}", f"{cap_code} {opt}")
        b.branded("tier_1", f"{opt} {cap_code}", opt)
        b.plain("tier_2", opt)
        b.branded("tier_2", opt)
        if tonnage := get_capacity_tonnage(cap_code, b.brand):
            b.plain("tier_3", f"{opt} {tonnage} TON", f"{opt} {tonnage}TON")
            b.branded("tier_3", f"{opt} {tonnage} TON")
        b.plain("tier_3", f"{opt} {cap_code}", f"{cap_code} {opt}")
        # Base-model tiers: strict search engines only answer short, human-like
        # queries.  Derive them structurally -- (a) the series blob with its
        # trailing aux tags stripped ("Sprinter T3" -> "Sprinter"), and (b) the
        # prefix cut at the first capacity-like token inside the blob
        # ("PINV 12K Turbo Ultimate T3" -> "PINV 12K").  Category-2 then decides
        # EXACT / BASE+notice / REJECT on whatever these queries retrieve.
        for form in _base_model_forms(opt):
            query = form if re.search(r"\d", form) else f"{cap_code} {form}"
            b.plain("tier_2", query)
            b.branded("tier_1", query)
    b.plain("tier_1", raw_model)
    b.branded("tier_1", raw_model)


def _base_model_forms(series: str) -> list[str]:
    """Structural short forms of a series blob: tag-stripped and capacity-cut."""
    toks = series.split()
    forms: list[str] = []
    while toks and is_sku_variant_tag(toks[-1]):
        toks = toks[:-1]
    if toks:
        forms.append(" ".join(toks))
    for i in range(1, len(toks)):
        if re.search(r"\d", toks[i]) and len(toks[i]) >= 3:
            forms.append(" ".join(toks[: i + 1]))
            break
    return list(dict.fromkeys(forms))


def _standard_model_patterns(
    b: _TierBuilder,
    *,
    clean_name: str,
    raw_model: str,
    bare_stem: str,
    aux_tag: str,
    prefix: str,
    stem_num: str,
) -> None:
    """Tier queries for standard alphanumeric model codes (washers, ACs, fridges)."""
    if b.brand:
        if prefix:
            b.branded(
                "tier_1",
                b.with_prefix(prefix, bare_stem, " "),
                b.with_prefix(prefix, bare_stem, "-"),
            )
            if stem_num and stem_num != bare_stem:
                b.branded(
                    "tier_1",
                    b.with_prefix(prefix, stem_num, " "),
                    b.with_prefix(prefix, stem_num, "-"),
                )
            b.branded("tier_1", raw_model)
            b.plain("tier_1", b.with_prefix(prefix, bare_stem, " "))
            if stem_num and stem_num != bare_stem:
                b.plain("tier_1", b.with_prefix(prefix, stem_num, " "))
                b.plain("tier_2", b.with_prefix(prefix, stem_num, "-"))
                if len(stem_num) >= 4:
                    b.plain("tier_2", stem_num)
                    b.branded("tier_2", stem_num)
            b.plain("tier_2", b.with_prefix(prefix, bare_stem, "-"))

        b.branded("tier_1", raw_model, bare_stem)
        b.branded("tier_2", bare_stem)

    # Pure numeric stems are never queried bare (they match shoes, clothes, etc.).
    if not bare_stem.isdigit():
        b.plain("tier_1", raw_model)
        if aux_tag and bare_stem not in b.tiers["tier_1"]:
            b.plain("tier_1", bare_stem)
        b.plain("tier_2", bare_stem)

    _, raw_color = normalize_color(clean_name, anchor=bare_stem)
    if raw_color:
        variants = (f"{bare_stem} {raw_color.title()}", f"{bare_stem} {raw_color}")
        b.plain("tier_1", *variants)
        b.branded("tier_1", *variants)

    _savein_patterns(b, bare_stem)

    if "-" in bare_stem:
        spaced, glued = bare_stem.replace("-", " "), bare_stem.replace("-", "")
        b.plain("tier_3", spaced, glued)
        if prefix and not bare_stem.upper().startswith(prefix):
            b.plain(
                "tier_3",
                f"{prefix}-{bare_stem}",
                f"{prefix} {bare_stem}",
                f"{prefix} {spaced}",
            )
    elif fridge := _FRIDGE_ANCHOR_RE.match(bare_stem):
        b.plain("tier_3", f"{fridge.group(1)} {fridge.group(2)}",
                f"{fridge.group(1)}-{fridge.group(2)}")
        b.branded("tier_3", bare_stem)

    if prefix and "-" not in bare_stem and not bare_stem.upper().startswith(prefix):
        b.plain("tier_3", f"{prefix}-{bare_stem}", f"{prefix} {bare_stem}")

    if m_suffix := _COLOR_SUFFIX_ANCHOR_RE.match(bare_stem):
        b.plain("tier_3", m_suffix.group(1))
    b.branded("tier_3", raw_model)


def _savein_patterns(b: _TierBuilder, bare_stem: str) -> None:
    """SaveIN <-> SVN <-> TAC-SVN equivalence queries (one place, all tiers)."""
    if not (
        re.search(r"Save[-_ ]?IN", bare_stem, re.IGNORECASE)
        or re.search(r"\bSVN\b", bare_stem, re.IGNORECASE)
        or re.search(r"\d+SVN", bare_stem, re.IGNORECASE)
    ):
        return
    svn = re.sub(r"Save[-_ ]?IN", "SVN", bare_stem, flags=re.IGNORECASE)
    savein = re.sub(r"SVN", "SaveIN", bare_stem, flags=re.IGNORECASE)
    tac_svn = b.with_prefix("TAC", svn, "-")
    no_tac_svn = re.sub(r"^TAC[-_]?", "", svn, flags=re.IGNORECASE)
    no_tac_savein = re.sub(r"^TAC[-_]?", "", savein, flags=re.IGNORECASE)

    b.plain("tier_1", svn, tac_svn, no_tac_svn, savein, no_tac_savein)
    b.branded("tier_1", svn, tac_svn, no_tac_svn, savein)
    b.plain("tier_2", svn, tac_svn, no_tac_svn, savein)
    b.branded("tier_2", svn, no_tac_svn)

    if m_cap := re.search(r"\b(\d{1,2})(?:SVN|SaveIN)", svn, re.IGNORECASE):
        cap = m_cap.group(1)
        b.plain("tier_3", f"{cap}SVN", f"TAC-{cap}SVN")
        b.branded("tier_3", f"{cap}SVN")


def _sane_query(query: str) -> str:
    """Drop the dangling separators a noise strip can leave behind ("SG -")."""
    return query.strip().strip("-|/ ,").strip()


def generate_search_patterns(canonical_name: str, brand: str = "") -> dict[str, list[str]]:
    """Generate tiered waterfall queries for every cartesian branch of a title."""
    clean_name = canonical_name.strip()
    # Search backends treat literal parentheses as noise: a query containing
    # "(G)" returns nothing even though a human typing the model finds the
    # product.  Unfold a parenthesised variant tag into a bare token so the
    # waterfall queries read like the listings do ("HSU-20HJUV G T3").
    clean_name = re.sub(r"[\(\[]([A-Za-z0-9]{1,2})[\)\]]", " ", clean_name)
    clean_name = re.sub(r"\s+-(?=[A-Za-z0-9])", " ", clean_name).strip()
    if not clean_name:
        return {"tier_1": [], "tier_2": [], "tier_3": []}

    branches = expand_cartesian_branches(clean_name)
    if len(branches) <= 1:
        return _generate_single_branch_patterns(clean_name, brand=brand)

    merged: dict[str, list[str]] = {"tier_1": [], "tier_2": [], "tier_3": []}
    for branch in branches:
        for tier, items in _generate_single_branch_patterns(branch, brand=brand).items():
            merged[tier].extend(items)
    return {tier: list(dict.fromkeys(items)) for tier, items in merged.items()}


# =============================================================================
# 8. SLOT EXTRACTION
# =============================================================================


def _anchor_from_prefix_match(m: re.Match[str], first_token_tag: str) -> tuple[str, str]:
    """Decide whether a ``PREFIX NUMBER SUFFIX`` hit is a real anchor."""
    pfx = m.group(1).upper()
    num = m.group(2)
    suf = re.sub(r"[()]", "", (m.group(3) or "").upper()).strip()
    if re.search(rf"^{re.escape(m.group(1))}\s+", m.group(0)) and suf:
        # Prefix was space-separated while num+suf form a digit-first model.
        return "", first_token_tag
    if num.isdigit() and len(num) <= 2 and (
        not suf or pfx in GENUINE_SUB_SERIES_TOKENS or pfx in {"SPLIT", "AUTO", "AWM"}
    ):
        return "", first_token_tag
    if pfx in NON_SKU_TOKENS:
        if not suf and not (num.isdigit() and len(num) <= 2):
            return num, first_token_tag
        return "", first_token_tag
    if suf and len(suf) <= 8 and suf not in {"INVERTER", "SERIES", "NORMAL"}:
        if is_sku_variant_tag(suf) and len(num) >= 3:
            return f"{pfx}-{num}", (first_token_tag or suf)
        return f"{pfx}-{num}{suf}", first_token_tag
    if not (num.isdigit() and len(num) <= 2):
        return f"{pfx}-{num}", first_token_tag
    return "", first_token_tag


_ANCHOR_PREFIX_RE = re.compile(r"\b([A-Za-z]{2,4})[-_ ]?(\d+(?:-\d+)?)[-_ ]?([A-Za-z0-9]*)\b")
_ANCHOR_ALNUM_RE = re.compile(r"\b(\d+[A-Za-z]+[A-Za-z0-9\-]*|[A-Za-z]+\d+[A-Za-z0-9\-]*)\b")
_ANCHOR_CAP_SERIES_RE = re.compile(r"\b(\d{1,2})\s+([A-Za-z0-9]+(?:-[A-Za-z0-9]+)?)\b")


def _extract_anchor(clean_title: str, brand: str, first_token: str) -> tuple[str, str]:
    """Primary model run for a title, plus any tag glued to its first token."""
    first_token_tag = ""
    if (
        re.search(r"\d", first_token)
        and not is_dimension_or_spec_token(first_token)
        and not (first_token.isdigit() and first_token in ALL_CAPACITY_CODES)
    ):
        if re.search(r"[\(\[]", first_token):
            # "HSU-20HJUV(G)-T3": the wrapped tag is a variant facet, not anchor
            # identity -- unfold it so the anchor core stays clean.
            pieces = [
                p.strip("-_.,")
                for p in re.sub(
                    r"[\(\[]([A-Za-z0-9]{1,2})[\)\]]", r" \1 ", first_token
                ).split()
                if p.strip("-_.,")
            ]
            core, first_token_tag = extract_tag(pieces[0]) if pieces else (first_token, "")
            for p in pieces[1:]:
                if is_sku_variant_tag(p) or p.upper() in GENUINE_SUB_SERIES_TOKENS:
                    first_token_tag = f"-{p}"
            return core, first_token_tag
        core, first_token_tag = extract_tag(first_token)
        return core, first_token_tag

    sub = clean_marketplace_noise(clean_title)
    if brand:
        abbr = re.escape(brand[:3]) if len(brand) >= 4 else "---"
        sub = re.sub(rf"^(?:{re.escape(brand)}|{abbr})[\s\-_,:]*", "", sub, flags=re.IGNORECASE)

    for m in _ANCHOR_PREFIX_RE.finditer(sub):
        anchor, tag = _anchor_from_prefix_match(m, first_token_tag)
        num_suf = f"{m.group(2)}{(m.group(3) or '').upper()}"
        if not anchor or is_dimension_or_spec_token(anchor) or is_dimension_or_spec_token(num_suf):
            continue
        return anchor, tag

    for m in _ANCHOR_ALNUM_RE.finditer(sub):
        cand = m.group(1).upper()
        if is_dimension_or_spec_token(cand):
            continue
        m_lead = re.search(rf"\b(\d{{1,2}})\s+{re.escape(m.group(1))}\b", sub)
        if m_lead and not cand[0].isdigit():
            return f"{m_lead.group(1)}{cand}", first_token_tag
        return cand, first_token_tag

    m_cap_series = _ANCHOR_CAP_SERIES_RE.search(sub)
    if (
        m_cap_series
        and m_cap_series.group(2).upper() not in NON_SKU_TOKENS
        and not is_sku_variant_tag(m_cap_series.group(2))
    ):
        w = m_cap_series.group(2)
        is_series_word = (
            (len(w) >= 4 and len(re.findall(r"[AEIOU]", w.upper())) >= 2)
            or w.upper() in GENUINE_SUB_SERIES_TOKENS
            or w.upper() in {"INVERTER", "SERIES", "NORMAL"}
        )
        if not is_series_word:
            return f"{m_cap_series.group(1)}{w.upper()}", first_token_tag
    return "", first_token_tag


@dataclass(frozen=True, slots=True)
class _SlotContext:
    """Everything a facet extractor may look at (built once per title)."""

    title: str
    anchor: str
    tokens: tuple[str, ...]
    brand: str
    is_display: bool
    is_non_ac: bool
    is_ac: bool

    @property
    def words(self) -> tuple[str, ...]:
        return tuple(self.title.split())


# --- facet extractors: one function per guarded facet --------------------------

_SCREEN_RE = re.compile(r"(?<![\d./])(\d{2})\s*-?\s*(?:INCH(?:ES)?\b|\"|\')", re.IGNORECASE)
_CFT_RE = re.compile(r"\b(\d+(?:\.\d+)?)\s*(?:CU\s*FT|CU\.FT|CFT)\b", re.IGNORECASE)
_KG_RE = re.compile(r"\b(\d+(?:\.\d+)?)\s*[-]?\s*KG\b", re.IGNORECASE)
_WASHER_ANCHOR_RE = re.compile(r"^(\d{2,3})-\d+")
_TON_RE = re.compile(r"\b(\d+(?:\.\d+)?)\s*[-]?\s*(?:TON|ΤΟN)\b", re.IGNORECASE)
_AC_LEAD_RE = re.compile(r"^(\d{2})[A-Za-z]")
_TAP_RE = re.compile(
    r"\b([1-4])\s*[-]?\s*(?:TAPS?|FAUCETS?)\b"
    r"|\b(SINGLE|TWO|THREE|FOUR|DOUBLE)\s*(?:TAPS?|FAUCETS?)\b",
    re.IGNORECASE,
)
_TAP_WORDS: dict[str, str] = {"SINGLE": "1", "TWO": "2", "DOUBLE": "2", "THREE": "3", "FOUR": "4"}
_TUB_RE = re.compile(r"\b\d+-\d+(WB|GB)\b|\b(WB|GB)\b", re.IGNORECASE)


def _facet_capacity(ctx: _SlotContext) -> str | None:
    """Screen inches -> cubic feet -> washer KG -> washer anchor KG -> AC tonnage."""
    if m := _SCREEN_RE.search(ctx.title):
        return f"{m.group(1)}INCH"
    if ctx.is_display and ctx.anchor and re.match(r"^(\d{2})[A-Z]\w{3,}$", ctx.anchor):
        return f"{ctx.anchor[:2]}INCH"
    if m := _CFT_RE.search(ctx.title):
        return f"{int(float(m.group(1)))}CFT"
    if m := _KG_RE.search(ctx.title):
        return f"{int(float(m.group(1)))}KG"
    if ctx.anchor and (m := _WASHER_ANCHOR_RE.match(ctx.anchor)):
        return f"{int(m.group(1)) // 10}KG"
    if ctx.is_non_ac:
        return None
    if m := _TON_RE.search(ctx.title):
        return f"{m.group(1)}T"
    if ctx.is_ac:
        for t in (*ctx.tokens, *ctx.words):
            if ton := get_capacity_tonnage(t.strip("-_., \"'"), ctx.brand):
                return f"{ton}T"
        if (
            ctx.anchor
            and (m := _AC_LEAD_RE.match(ctx.anchor))
            and (ton := get_capacity_tonnage(m.group(1), ctx.brand))
        ):
            return f"{ton}T"
    return None


def _facet_capacity_fallback(ctx: _SlotContext, capacity: str | None) -> str | None:
    """Water-dispenser tap count, used only when no other capacity was found."""
    if capacity or not (m := _TAP_RE.search(ctx.title)):
        return capacity
    val = m.group(1) or m.group(2)
    return f"{_TAP_WORDS.get(val.upper(), val)}TAP"


def _facet_tub_series(ctx: _SlotContext) -> str | None:
    m = _TUB_RE.search(ctx.title)
    return (m.group(1) or m.group(2)).upper() if m else None


def _facet_color(ctx: _SlotContext) -> tuple[str | None, str | None]:
    return normalize_color(ctx.title, anchor=ctx.anchor)


def _operating_mode(ctx: _SlotContext) -> tuple[bool | None, bool | None]:
    cool = bool(
        re.search(r"\b(?:COOL\s+ONLY|COOLING\s+ONLY|ONLY\s+COOL)\b", ctx.title, re.IGNORECASE)
    ) or None
    heat = bool(
        re.search(r"\b(?:HEAT\s*(?:&|AND|/)\s*COOL|H\s*&\s*C|H/C)\b", ctx.title, re.IGNORECASE)
    ) or None
    return cool, heat


def _facet_door_finish(ctx: _SlotContext) -> str | None:
    if re.search(r"\b(?:GD|GLASS\s+DOOR)\b", ctx.title, re.IGNORECASE):
        return "GD"
    if re.search(r"\b(?:INOX|STAINLESS(?:\s+STEEL)?|S\.S)\b", ctx.title, re.IGNORECASE):
        return "INOX"
    return None


def _facet_door_type(ctx: _SlotContext) -> str | None:
    if re.search(r"\b(?:SD|SINGLE\s+DOOR)\b", ctx.title, re.IGNORECASE):
        return "SD"
    if re.search(r"\b(?:DD|DOUBLE\s+DOOR)\b", ctx.title, re.IGNORECASE):
        return "DD"
    return None


def _facet_inverter(ctx: _SlotContext) -> bool | None:
    if re.search(
        r"\b(?:NON[\s\-]*INVERTER|FIX(?:ED)?\s*SPEED|CONVENTIONAL)\b", ctx.title, re.IGNORECASE
    ):
        return False
    if re.search(r"\b(?:INVERTER|INV|DC\s*INVERTER|SAVEIN)\b", ctx.title, re.IGNORECASE) or (
        ctx.anchor and re.search(r"(?:SVN|INV)", ctx.anchor, re.IGNORECASE)
    ):
        return True
    return None


# Tokens owned by a dedicated orthogonal slot -- they must not also become capabilities.
_DEDICATED_SLOTS: frozenset[str] = frozenset(
    {"GD", "INOX", "DD", "INVERTER", "INV", "WB", "GB", "GC", "FH", "CHROME", "LVS"}
)
_GLUED_TAG_RE = re.compile(r"\b[A-Za-z]{0,4}(\d{3,})([A-Za-z]{2,4})\b")


def _text_after_anchor(clean_title: str, anchor: str) -> str | None:
    """Text strictly after the anchor (trying hyphen / space / glued variants)."""
    if not anchor:
        return None
    variants = [anchor]
    if "-" in anchor:
        variants += [anchor.replace("-", " "), anchor.replace("-", "")]
    upper = clean_title.upper()
    for v in variants:
        if (idx := upper.find(v.upper())) != -1:
            return clean_title[idx + len(v):]
    return None


def _post_anchor_words(ctx: _SlotContext) -> list[str]:
    tail = _text_after_anchor(ctx.title, ctx.anchor)
    if (
        tail is None
        and (m := re.search(r"\d{3,}", ctx.anchor))
        and (idx := ctx.title.find(m.group(0))) != -1
    ):
        tail = ctx.title[idx + len(m.group(0)):]
    return tail.split() if tail else []


def _facet_capabilities(ctx: _SlotContext, first_token_tag: str) -> set[str]:
    """Category-2 modifiers: harvested from the *contiguous* post-model code run.

    BUG FIX (RC-3): the old scan walked the entire descriptive tail and treated any
    2-4 letter word as a hardware capability, so a vendor's fuller SKU suffix
    (``... Prima Series DDM ...``) was read as an *extra* capability and hard-rejected
    the listing.  Now:
      * codes containing a digit (T3, ES8, S6) are unambiguous -> accepted anywhere;
      * pure-alphabetic codes are only guarded when they sit in the contiguous run
        directly after the model, or are glued to the numeric stem.
    """
    caps: set[str] = set()
    if re.search(r"\b(?:WIFI|WI-FI)\b", ctx.title, re.IGNORECASE):
        caps.add("WIFI")
    if re.search(r"\bIOT\b", ctx.title, re.IGNORECASE) or (
        not ctx.is_display
        and not re.search(r"\b(?:WIFI|WI-FI)\b", ctx.title, re.IGNORECASE)
        and re.search(r"\bSMART\b", ctx.title, re.IGNORECASE)
    ):
        caps.add("IOT")

    ordered: list[tuple[str, bool]] = []  # (token, contiguous_with_anchor)

    tag = first_token_tag.strip("()[]{}-.,_ \"'/").upper()
    if tag and is_sku_variant_tag(tag):
        ordered.append((tag, True))

    if ctx.anchor and "-" in ctx.anchor:
        parts = ctx.anchor.split("-")
        if (
            len(parts) > 1
            and any(re.search(r"\d", p) for p in parts[:-1])
            and is_sku_variant_tag(parts[-1])
        ):
            ordered.append((parts[-1].upper(), True))

    post_model = (
        ctx.tokens[2:]
        if (len(ctx.tokens) >= 2 and ctx.tokens[0].isdigit() and len(ctx.tokens[0]) <= 2)
        else ctx.tokens[1:]
    )
    ordered += [
        (t, True)
        for t in (
            x.strip("()[]{}-.,_ \"'/").upper()
            for x in post_model
            # A wrapped variant tag ("(OW)") belongs to the variant_tag slot,
            # not to capabilities -- else it double-guards and false-BASEs.
            if not re.fullmatch(r"[\(\[][A-Za-z]{1,2}[\)\]]", x.strip())
        )
        if t and is_sku_variant_tag(t)
    ]

    contiguous = True
    for w in _post_anchor_words(ctx):
        if re.fullmatch(r"[\(\[][A-Za-z]{1,2}[\)\]]", w.strip()):
            continue  # wrapped variant tag -> variant_tag slot, not capabilities
        w_clean = w.strip("()[]-.,_ \"'/").upper()
        if not w_clean:
            continue  # a bare separator ('/', '-') does not end the code run
        if is_sku_variant_tag(w_clean):
            ordered.append((w_clean, contiguous))
        elif "-" in w:
            sub = w.split("-")[-1].strip("()[]-.,_ \"'/").upper()
            if is_sku_variant_tag(sub):
                ordered.append((sub, contiguous))
                continue
            contiguous = False
        else:
            # The run ends at the first real word: from here the title is series /
            # colour / descriptive prose, not model-code territory.
            contiguous = False

    if m := _GLUED_TAG_RE.search(ctx.title):
        glued = m.group(2).strip("()[]{}").upper()
        if is_sku_variant_tag(glued):
            ordered.append((glued, True))

    anchor_core, _ = extract_tag(ctx.anchor) if ctx.anchor else ("", "")
    norm_anchor = anchor_core.replace("-", "").upper()

    for tok, is_contiguous in ordered:
        if tok in _DEDICATED_SLOTS or tok in CATEGORY_1_DIRECT_MATCH_MODIFIERS:
            continue
        if norm_anchor and tok in norm_anchor:
            continue
        # RC-3: ambiguous pure-alphabetic codes need anchor adjacency.
        if not is_contiguous and not re.search(r"\d", tok):
            continue
        caps.add(tok)
    return caps


_RESIDUAL_RE = re.compile(
    r"\b(?:GC|GLASS\s+DOOR|CLEAR\s+LID|PILLOW\s+DRUM)\b", re.IGNORECASE
)


def _extract_residuals(ctx: _SlotContext) -> list[str]:
    residuals: list[str] = []
    if m := _RESIDUAL_RE.search(ctx.title):
        residuals.append(m.group(0).upper())
    if ctx.anchor:
        tail = _text_after_anchor(ctx.title, ctx.anchor)
        source = tail.split() if tail is not None else list(ctx.tokens[1:])
        for t in source:
            t_c = t.strip("-.,_ \"'")
            if is_sku_variant_tag(t_c) and t_c.upper() not in residuals:
                residuals.append(t_c.upper())
    return list(dict.fromkeys(residuals))


# Ordered strip patterns for series extraction by residual subtraction (ADR-002).
_SERIES_STRIP_TECH_RE = re.compile(
    r"\b(?:NON[\s\-]*INVERTER|FIX(?:ED)?\s*SPEED|CONVENTIONAL|T3|INVERTER|INV|4K|SMART"
    r"|WIFI|WI-FI|IOT|FHD|HD|SPLIT|AC|AUTO|TOP\s+LOAD|FRONT\s+LOAD|FULLY\s*[-\s]?\s*AUTOMATIC"
    r"|SEMI\s*[-\s]?\s*AUTOMATIC|AUTOMATIC|AAA\+|AA\+|A\+{1,3}|AAA|AA)\b",
    re.IGNORECASE,
)
_CFT_STRIP_RE = re.compile(r"\b(?:\d+(?:\.\d+)?\s*(?:CU\s*FT|CU\.FT|CFT|CU))\b", re.IGNORECASE)


def _extract_series(
    ctx: _SlotContext,
    residuals: list[str],
    caps: set[str],
    tub_series: str | None,
    capacity: str | None,
) -> str:
    """Series = title - (brand U category U specs U colours U anchor U tags).

    Residual subtraction (ADR-002): nothing is looked up in a series dictionary, the
    series is whatever survives once every closed-domain token has been removed.
    """
    sub = re.sub(r"\([^)]*\)", " ", clean_marketplace_noise(ctx.title))
    sub = CATEGORY_PATTERNS.sub(" ", sub)
    sub = _CFT_STRIP_RE.sub(" ", sub)
    sub = re.sub(r"\b(?:SINGLE\s*TUB)\b", " ", sub, flags=re.IGNORECASE)

    strips: list[str] = []
    if ctx.brand:
        strips.append(rf"\b{re.escape(ctx.brand)}\b")
    if ctx.anchor:
        strips += [
            rf"\b[A-Za-z]{{2,4}}[- ]?{re.escape(ctx.anchor)}\b",
            rf"\b{re.escape(ctx.anchor)}\b",
            rf"\b{re.escape(ctx.anchor.replace('-', ''))}[A-Za-z0-9]*\b",
            *(rf"\b{re.escape(p)}\b" for p in re.findall(r"[A-Za-z]+|\d+", ctx.anchor) if p),
        ]
        anchor_prefix = ctx.anchor.split("-")[0]
        if "-" in ctx.anchor and len(anchor_prefix) <= 4:
            strips.append(rf"\b{re.escape(anchor_prefix)}\b")
        stem = ctx.anchor.split("-")[-1]
        if stem.isdigit() and len(stem) >= 3:
            strips.append(rf"\b{re.escape(stem)}[A-Za-z0-9]*\b")
    strips.append(r"\b[A-Za-z]{2,4}-\d+")
    for pattern in strips:
        sub = re.sub(pattern, " ", sub, flags=re.IGNORECASE)

    sub = _SERIES_STRIP_TECH_RE.sub(" ", sub)
    for tok in (
        *( [tub_series] if tub_series else [] ),
        *residuals,
        *caps,
        *CATEGORY_1_DIRECT_MATCH_MODIFIERS,
    ):
        sub = re.sub(rf"\b{re.escape(tok)}\b", " ", sub, flags=re.IGNORECASE)

    shade = _color_shade(ctx.title, anchor=ctx.anchor)
    sub = " ".join(
        tok
        for tok in sub.split()
        if tok.upper() not in ALL_COLOR_WORDS
        and not is_color_token(tok)
        and tok.upper() != shade  # shade lives in the colour slot, never in series
    )
    if ctx.anchor:
        sub = re.sub(rf"\b{re.escape(ctx.anchor)}\b", " ", sub, flags=re.IGNORECASE)
    if cap_num := re.sub(r"[^0-9.]", "", capacity or ""):
        sub = re.sub(rf"\b{re.escape(cap_num)}\b", " ", sub)
    for code in ALL_CAPACITY_CODES:
        sub = re.sub(rf"\b{code}\b", " ", sub)
    return _finish_series(sub)


def _finish_series(sub: str) -> str:
    tokens = [
        tok
        for tok in (t if t == "/" else t.strip("-.,_ \"'+") for t in sub.split())
        if tok
        and (
            tok == "/"
            or (tok.upper() not in NON_SKU_TOKENS and len(tok) > 1 and not tok.isdigit())
        )
    ]
    return re.sub(r"\s*/\s*", " / ", " ".join(tokens)).strip().strip(" /").strip()


def extract_product_slots(title: str, brand: str = "") -> ProductSlots:
    """Factor a catalog target or marketplace title into the 4 orthogonal slots."""
    raw = title.strip().translate(_HOMOGLYPHS)
    for trailer in (
        r"\s*[-–—|]\s*(?:By\s+|Official\s+)[A-Za-z0-9\s.]{2,}$",
        r"\s*[-–—|]\s*(?:HomeCart|ElectroEase|Telemart|Metro|Hyperstar|AlfaMall"
        r"|Faysal Bank|QistBazaar)\b.*$",
    ):
        raw = re.sub(trailer, "", raw, flags=re.IGNORECASE)
    # A model code glued onto the tail of a longer word is still a model code:
    # "...Washing MachineDwt-1166" must surface "DWT-1166" as the anchor.
    raw = re.sub(r"(?<=[a-z])([A-Z][A-Za-z]{1,3}[-_]\d)", r" \1", raw)
    clean_title = normalize_technical_slashes(MERCHANT_TRACKING_CODE_RE.sub(" ", raw))
    # Read the parenthesised variant tag from the FULL title: prose-trimming
    # below may drop a "| (G) |" segment, but the tag is part of the identity.
    variant_tag = _paren_variant_tag(clean_title)

    detected_brand = detect_brand(clean_title, brand)
    _, raw_model = extract_search_query_and_model(clean_title, brand=detected_brand)

    # Marketing prose after a pipe or long dash is not model identity
    # ("… WFL—Extra Large Single Tub Washer | Powerful Washing | Built-in Buzzer"),
    # so it must not reach the series slot.  But a listing may legitimately put
    # the model code *after* the separator ("GREE AIR CONDITIONER INVERTER 1.5 TON
    # | 18AITH21W"), so only cut the trailing prose once the extracted model no
    # longer appears in it -- never before.
    prose = re.compile(r"\s*(?:[|–—].*)+$")
    trimmed = prose.sub("", clean_title).strip()
    if trimmed and trimmed != clean_title:
        if raw_model and raw_model.upper() not in trimmed.upper():
            # The model code itself lives in the trailing segment; keep it and
            # discard only the words around it.
            trimmed = f"{trimmed} {raw_model}"
        clean_title = trimmed
        _, raw_model = extract_search_query_and_model(clean_title, brand=detected_brand)
    tokens = tuple(raw_model.split())

    anchor, first_token_tag = _extract_anchor(
        clean_title, detected_brand, tokens[0] if tokens else raw_model
    )
    # A listing may wrap the model in parentheses ("... 1.5 Ton (GS-18PITC12W-T3)");
    # the wrapping punctuation is not part of the model identity.  A tag wrapped
    # *inside* the model run ("HSU-20HJUV(G)") leaves a dangling "(" which is
    # likewise punctuation, not identity.
    anchor = re.sub(r"[^A-Za-z0-9]+$", "", anchor.strip("()[]{}"))

    is_non_ac = bool(
        re.search(
            r"\b(?:CU\s*FT|CU\.FT|CFT|REFRIGERATOR|FRIDGE|WASHER|WASHING|DISPENSER|OVEN"
            r"|MICROWAVE)\b",
            clean_title,
            re.IGNORECASE,
        )
    )
    has_ac_keyword = bool(
        re.search(r"\b(?:AC|SPLIT|INVERTER|INV|T3|TON|ΤΟN)\b", clean_title, re.IGNORECASE)
    )
    has_ac_cap_code = any(t in ALL_CAPACITY_CODES for t in clean_title.split())
    is_display = bool(
        re.search(
            r"\b(?:LED|TV|TELEVISION|MONITOR|DISPLAY|SMART\s*TV|OLED|QLED|UHD|FHD)\b",
            clean_title,
            re.IGNORECASE,
        )
    ) or bool(_SCREEN_RE.search(clean_title))
    ctx = _SlotContext(
        title=clean_title,
        anchor=anchor,
        tokens=tokens,
        brand=detected_brand,
        is_display=is_display,
        is_non_ac=is_non_ac,
        is_ac=(has_ac_keyword or has_ac_cap_code) and not is_non_ac,
    )

    capacity = _facet_capacity_fallback(ctx, _facet_capacity(ctx))
    tub_series = _facet_tub_series(ctx)
    color_family, color_raw = _facet_color(ctx)
    color_shade = _color_shade(ctx.title, anchor=anchor)
    cool_only, heat_and_cool = _operating_mode(ctx)
    capabilities = _facet_capabilities(ctx, first_token_tag)
    residuals = _extract_residuals(ctx)

    return ProductSlots(
        anchor=anchor,
        series=_extract_series(ctx, residuals, capabilities, tub_series, capacity),
        guarded_facets=GuardedFacets(
            capacity=capacity,
            tub_series=tub_series,
            color_family=color_family,
            color_raw=color_raw,
            color_shade=color_shade,
            door_finish=_facet_door_finish(ctx),
            cool_only=cool_only,
            heat_and_cool=heat_and_cool,
            door_type=_facet_door_type(ctx),
            is_inverter=_facet_inverter(ctx),
            variant_tag=variant_tag,
            capabilities=capabilities,
        ),
        residuals=residuals,
    )


# =============================================================================
# 9. REFEREE  (declarative guard table -- one row per guarded facet)
# =============================================================================


@dataclass(frozen=True, slots=True)
class _FacetRule:
    """One guarded facet: how to read it, and what to say on collision / omission."""

    label: str
    get: Callable[[GuardedFacets], Any]
    collision: str
    omission: str | None = None
    render: Callable[[Any], str] = str
    omit_only_when_true: bool = False
    missing_render: Callable[[Any], str] | None = None
    equivalent: Callable[[Any, Any], bool] | None = None
    context: Callable[[GuardedFacets, Any], dict[str, str]] | None = None

    def collides(self, target: Any, cand: Any) -> bool:
        if target is None or cand is None:
            return False
        if self.equivalent is not None:
            return not self.equivalent(target, cand)
        return bool(target != cand)

    def is_omitted(self, target: Any, cand: Any) -> bool:
        if self.omission is None:
            return False
        if self.omit_only_when_true:
            return target is True and cand is None
        return target is not None and cand is None


def _operating_mode_value(f: GuardedFacets) -> str | None:
    if f.cool_only:
        return "COOL_ONLY"
    if f.heat_and_cool:
        return "HEAT_AND_COOL"
    return None


_MODE_LABELS = {"COOL_ONLY": "Cool Only", "HEAT_AND_COOL": "Heat & Cool"}


def _render_mode(v: Any) -> str:
    return _MODE_LABELS.get(str(v), str(v))


def _render_inverter(v: Any) -> str:
    return "Inverter" if v else "Non-Inverter"


def _norm_capacity(c: Any) -> float | str:
    digits = re.sub(r"[^0-9.]", "", str(c))
    try:
        return float(digits)
    except ValueError:
        return digits


def _capacity_equivalent(a: Any, b: Any) -> bool:
    return _norm_capacity(a) == _norm_capacity(b)


def _color_context(f: GuardedFacets, value: Any) -> dict[str, str]:
    return {"raw": f.color_raw or ""}


# A short *alphabetic* tag wrapped in parentheses anywhere in a listing is a
# finish/variant code ("HSU-20HJUV(G)", "HSU-19HFS (G) T3", "(OW)"): the corpus
# shows exactly G/W/OW/DG/GE.  Length-capped at 2 so marketing parens such as
# "(NEW)" / "(IOT)" never enter the identity slots; digits excluded so "(12)"
# style counts never do.  No brand or colour vocabulary is consulted.
_PAREN_VARIANT_TAG_RE = re.compile(r"[\(\[]\s*([A-Za-z]{1,2})\s*[\)\]]")


def _paren_variant_tag(text: str) -> str | None:
    m = _PAREN_VARIANT_TAG_RE.search(text)
    return m.group(1).upper() if m else None


def _reconcile_variant_tags(
    target: ProductSlots, cand: ProductSlots
) -> tuple[ProductSlots, ProductSlots]:
    """Fold a *glued* spelling of the variant tag into the same slot as '(X)'.

    ``HSU-20HJUVGT3`` squashes to the other side's anchor plus one or two
    trailing letters; that tail is the same tag a parenthesis would carry, so
    move it out of the anchor and into ``variant_tag`` on both spellings.
    Purely structural: only fires when one squashed anchor is a proper prefix
    of the other with a short alphabetic difference.
    """
    slots = [target, cand]
    for i, j in ((0, 1), (1, 0)):
        long_side, short_side = slots[i], slots[j]
        nl, ns = _squash(long_side.anchor), _squash(short_side.anchor)
        if not ns or len(nl) <= len(ns) or not nl.startswith(ns):
            continue
        diff = nl[len(ns):]
        if not (1 <= len(diff) <= 2 and diff.isalpha()):
            continue
        if long_side.guarded_facets.variant_tag is not None:
            continue
        new_anchor = re.sub(re.escape(diff) + r"$", "", long_side.anchor, flags=re.IGNORECASE)
        slots[i] = _replace(
            long_side,
            anchor=new_anchor,
            guarded_facets=_replace(long_side.guarded_facets, variant_tag=diff.upper()),
        )
    return slots[0], slots[1]


# Evaluation order is significant and mirrors ADR-002: hardware identity first,
# then the anchor, then the series, then additive capabilities, then cosmetics.
_FACET_RULES: tuple[_FacetRule, ...] = (
    _FacetRule(
        "tub",
        lambda f: f.tub_series,
        "Hardware tub mismatch: {t} vs {c}",
    ),
    _FacetRule(
        "door_finish",
        lambda f: f.door_finish,
        "Hardware finish collision: target is {t} vs candidate {c}",
        omission=(
            "Hardware finish omitted ({t} mismatch): Target specifies {t} "
            "but candidate does not"
        ),
    ),
    _FacetRule(
        "door_type",
        lambda f: f.door_type,
        "Door structure collision: target is {t} vs candidate {c}",
    ),
    _FacetRule(
        "inverter",
        lambda f: f.is_inverter,
        "Inverter mode collision: target is {t} vs candidate {c}",
        omission=(
            "Hardware capability omitted (INVERTER mismatch): Target specifies INVERTER "
            "but candidate does not"
        ),
        omit_only_when_true=True,
        render=_render_inverter,
        missing_render=lambda v: "INVERTER",
    ),
    _FacetRule(
        "operating_mode",
        _operating_mode_value,
        "Operating mode collision: Target is {t} vs Candidate is {c}",
        render=_render_mode,
    ),
)

_POST_FACET_RULES: tuple[_FacetRule, ...] = (
    _FacetRule(
        "variant_tag",
        lambda f: f.variant_tag,
        "Variant tag collision: ({t}) vs ({c})",
        omission=(
            "Variant tag omitted: target specifies ({t}) but candidate does not"
        ),
    ),
    _FacetRule(
        "capacity",
        lambda f: f.capacity,
        "Capacity / screen size mismatch: {t} vs {c}",
        equivalent=_capacity_equivalent,
    ),
    _FacetRule(
        "color",
        lambda f: f.color_family,
        "Color collision: {t_raw} ({t}) vs {c_raw} ({c})",
        context=_color_context,
    ),
    _FacetRule(
        "color_shade",
        lambda f: f.color_shade,
        "Color shade collision: {t} vs {c}",
        omission=(
            "Color shade omitted: target specifies {t} but candidate does not"
        ),
    ),
)


def _reject(
    reason: str, target: ProductSlots, cand: ProductSlots, *, base: bool = False,
    missing: str | None = None,
) -> MatchDecision:
    return MatchDecision(
        is_match=False,
        reason=reason,
        target_slots=target,
        candidate_slots=cand,
        is_base_match=base,
        missing_modifier=missing,
    )


def _run_rules(
    rules: Iterable[_FacetRule], target: ProductSlots, cand: ProductSlots
) -> MatchDecision | None:
    """Apply a rule table; return the first collision/omission verdict, else None.

    Two passes by design: a *declared conflict* on any facet (H&C vs COOL ONLY,
    Ruby vs Diamond) must REJECT even when another facet is merely omitted.
    An omission (soft, BASE + notice) can never mask a hard collision -- the
    Category-2 doctrine is "collisions beat omissions".
    """
    tf, cf = target.guarded_facets, cand.guarded_facets
    ruled = list(rules)

    def fields_for(rule: _FacetRule, tv: Any, cv: Any) -> dict[str, Any]:
        fields: dict[str, Any] = {"t": rule.render(tv), "c": rule.render(cv)}
        if rule.context is not None:
            fields.update({f"t_{k}": v for k, v in rule.context(tf, tv).items()})
            fields.update({f"c_{k}": v for k, v in rule.context(cf, cv).items()})
        return fields

    for rule in ruled:  # pass 1: hard collisions
        tv, cv = rule.get(tf), rule.get(cf)
        if rule.collides(tv, cv):
            return _reject(rule.collision.format(**fields_for(rule, tv, cv)), target, cand)
    for rule in ruled:  # pass 2: omissions -> BASE fallback + notice
        tv, cv = rule.get(tf), rule.get(cf)
        if rule.is_omitted(tv, cv):
            missing = (rule.missing_render or rule.render)(tv)
            return _reject(
                rule.omission.format(**fields_for(rule, tv, cv)),  # type: ignore[union-attr]
                target,
                cand,
                base=True,
                missing=missing,
            )
    return None


_ANCHOR_EQUIVALENCE = (("SAVEIN", "SVN"),)


def _anchor_branches(anchor: str) -> tuple[str, ...]:
    """Every single-branch form of a multi-variant anchor.

    ``HSU-13HFS/013WDC(G)`` is one product with two orderable branches, so a
    listing may legitimately write either ``HSU-13HFS(G)`` or ``HSU-013WDC(G)``.
    ``GS-24PITH15/16/17/18G`` collapses its digit list onto the first member.
    """
    parts = [p.strip() for p in anchor.split("/")]
    if len(parts) < 2:
        return ()
    out: list[str] = []
    for i, branch in enumerate(parts):
        if not branch:
            continue
        if re.fullmatch(r"\d+", branch):
            # Bare digit run: either a continuation (16, 17) or the tail that
            # carries the shared suffix (18G).  Attach it to the previous branch
            # only when it is the final part.
            if i + 1 == len(parts) and out:
                out[-1] += branch
            continue
        out.append(branch)
    return tuple(_squash(p) for p in dict.fromkeys(out) if _squash(p))


def _anchor_equivalents(norm: str, anchor: str = "") -> tuple[str, ...]:
    out = [norm]
    if anchor and "/" in anchor:
        out.extend(_anchor_branches(anchor))
    for a, b in _ANCHOR_EQUIVALENCE:
        for base in list(out):
            if a in base:
                out.append(base.replace(a, b))
            elif b in base:
                out.append(base.replace(b, a))
    return tuple(dict.fromkeys(out))


def _anchor_verdict(
    target: ProductSlots, cand: ProductSlots, candidate_title: str, brand: str
) -> MatchDecision | None:
    """Anchor identity check.  Returns a REJECT decision or None when it matches."""
    if not target.anchor:
        return None

    norm_t = _squash(target.anchor)
    norm_title = _squash(candidate_title)
    norm_c = _squash(cand.anchor) if cand.anchor else ""
    # The variant tag lives in its own slot now; re-attach it for branch-shape
    # arithmetic so "HSU-13HFS(G)" still reads as a branch of
    # "HSU-13HFS/013WDC(G)".  Kept OUT of the suffix-collision check: a tag
    # *omission* (one side bare) must fall through to the BASE notice, not
    # masquerade as a letter collision.
    tagged_t = norm_t + (target.guarded_facets.variant_tag or "")
    tagged_c = norm_c + (cand.guarded_facets.variant_tag or "")
    t_nums = re.findall(r"\d{2,}", norm_t)
    c_nums = re.findall(r"\d{2,}", norm_c)
    t_eq = _anchor_equivalents(norm_t, target.anchor)
    c_eq = _anchor_equivalents(norm_c, cand.anchor)

    matched = False
    # One branch of a multi-variant anchor *is* the product, so it must short-circuit
    # the numeric-count heuristic below (which would compare ['13','013'] with ['13']).
    multi_branch = "/" in target.anchor or "/" in cand.anchor
    if cand.anchor and multi_branch and (
        any(a == b for a in t_eq for b in c_eq)
        or _is_branch_form(tagged_t, tagged_c)
        or _is_branch_form(_strip_lead_alpha(tagged_t), tagged_c)
        or _is_branch_form(tagged_c, tagged_t)
    ):
        matched = True
    if cand.anchor and not matched:
        overlaps = (
            norm_t == norm_c
            or any(a == b for a in t_eq for b in c_eq)
            or any(a in b for a in t_eq for b in c_eq)
            or (len(norm_c) >= 3 and any(b in a for a in t_eq for b in c_eq))
            or norm_t in norm_title
        )
        if overlaps:
            if t_nums and c_nums and len(t_nums) > 1 and len(c_nums) > 1:
                # A multi-branch anchor ("HSU-13HFS/013WDC(G)") legitimately
                # presents as a single branch, so a candidate numeric set that is
                # a subset of the target's is the same product, not a conflict.
                matched = set(t_nums) == set(c_nums) or set(c_nums) <= set(t_nums)
            elif t_nums and c_nums and len(t_nums) == 1 and len(c_nums) == 1:
                matched = t_nums[0] == c_nums[0]
            elif t_nums and c_nums and len(t_nums) > 1 and len(c_nums) == 1:
                matched = bool(
                    re.search(
                        rf"\b{re.escape(target.anchor)}\b", candidate_title, re.IGNORECASE
                    )
                ) or (
                    target.guarded_facets.capacity is not None
                    and cand.guarded_facets.capacity is not None
                    and target.guarded_facets.capacity == cand.guarded_facets.capacity
                    and "INCH" in target.guarded_facets.capacity
                )
            else:
                matched = True
        elif t_nums and c_nums:
            if len(t_nums) > 1 and len(c_nums) > 1:
                matched = set(t_nums) == set(c_nums)
            elif len(t_nums) == 1 and len(c_nums) == 1:
                matched = t_nums[0] == c_nums[0]
            elif len(t_nums) == 1 and t_nums[0] in c_nums:
                matched = True
    elif norm_t in norm_title:
        matched = True
    elif not cand.anchor:
        t_big = re.findall(r"\d{3,}", norm_t)
        matched = len(t_big) == 1 and t_big[0] in norm_title

    # Dynamic brand-initial prefix synthesis (Haier '11LF' vs listing 'HRF-11LF').
    if not matched and brand:
        b_init = brand[0].upper()
        if re.search(rf"{b_init}[A-Z]{{1,3}}{re.escape(norm_t)}", norm_title):
            matched = True
        elif (
            cand.anchor
            and norm_t.startswith(b_init)
            and norm_c.startswith(b_init)
        ):
            core_t = re.sub(r"^[A-Z]{2,4}", "", norm_t)
            core_c = re.sub(r"^[A-Z]{2,4}", "", norm_c)
            if core_t and core_c and (
                core_t == core_c or core_t in core_c or core_c in core_t
            ):
                matched = True

    # A multi-variant anchor and one of its own branches are the same product, so
    # the differing trailing runs are not a variant-tag collision.
    same_branch_family = ("/" in target.anchor or "/" in cand.anchor) and (
        _is_branch_form(tagged_t, tagged_c) or _is_branch_form(tagged_c, tagged_t)
    )
    if (
        cand.anchor
        and not same_branch_family
        and (collision := _anchor_tag_collision(norm_t, norm_c)) is not None
    ):
        return _reject(collision, target, cand)

    if not matched:
        return _reject(
            f"Anchor model mismatch: {target.anchor} vs {cand.anchor or candidate_title}",
            target,
            cand,
        )
    return None


def _strip_lead_alpha(norm: str) -> str:
    """Drop a leading brand-initial run: ``HSU13HFS013WDCG`` -> ``13HFS013WDCG``."""
    return re.sub(r"^[A-Z]{2,4}", "", norm)


def _is_branch_form(norm_t: str, norm_c: str) -> bool:
    """True when ``norm_c`` is a single-branch spelling of ``norm_t``.

    ``HSU-13HFS/013WDC(G)`` is one product with two orderable branches, so a
    listing may legitimately write ``HSU-13HFS(G)``.  Squashed, that is the
    target's own leading run plus its own trailing run with the other branch
    removed -- no brand vocabulary required to recognise it.
    """
    if len(norm_c) >= len(norm_t):
        return False
    return any(
        norm_t.startswith(norm_c[:k]) and norm_t.endswith(norm_c[k:])
        for k in range(3, len(norm_c))
    )


def _anchor_tag_collision(norm_t: str, norm_c: str) -> str | None:
    """Variant-tag and generation-code collisions inside the anchor itself."""
    if len(norm_t) >= 4 and len(norm_c) >= 4:
        suf_t, suf_c = norm_t[-2:], norm_c[-2:]
        if suf_t.isalpha() and suf_c.isalpha() and norm_t[:2] == norm_c[:2] and suf_t != suf_c:
            return f"Variant tag collision: {norm_t} vs {norm_c}"
        gen_t = re.search(r"([A-Z]\d)$", norm_t)
        gen_c = re.search(r"([A-Z]\d)$", norm_c)
        if gen_t and gen_c and gen_t.group(1) != gen_c.group(1):
            return (
                f"Generation series collision: {gen_t.group(1)} vs {gen_c.group(1)} "
                f"({norm_t} vs {norm_c})"
            )
    return None


def _comparison_words(text: str) -> set[str]:
    """Token set for series comparison: alnum runs *and* whole-token compounds.

    ``E-Star`` tokenises to ``E`` + ``STAR`` under a plain ``[A-Z0-9]+`` scan, which made
    an identical target/candidate series read as "missing".  Deliberately *not* extended
    with multi-token n-grams: this set also drives sub-series set arithmetic, where extra
    compounds would invent "extra sub-series" collisions that do not exist.
    """
    up = text.upper()
    return set(re.findall(r"[A-Z0-9]+", up)) | {_squash(w) for w in up.split() if _squash(w)}


def _comparison_ngrams(text: str, span: int = 3) -> set[str]:
    """Squashed contiguous token runs, for *coverage* tests only.

    A series name may be only part of a longer hyphenated code -- ``MSEZ2D-24HRFN1``
    inside ``MSEZ2D-24HRFN1-QCOW-B`` -- so coverage has to look at joined runs.  The
    window is bounded on purpose: unbounded substring matching would let a series like
    ``PRO`` match inside ``PROCESSOR``.
    """
    tokens = [w for w in (_squash(w) for w in text.upper().split()) if w]
    return {
        "".join(tokens[i : i + n])
        for n in range(2, span + 1)
        for i in range(len(tokens) - n + 1)
    }


def _series_covered(alt: str, cand_words: set[str], cand_ngrams: set[str]) -> bool:
    """True when every token of the series alternative is present in the candidate."""
    alt_words = set(re.findall(r"[A-Z0-9]+", alt.upper()))
    if alt_words:
        return alt_words <= cand_words
    # No ASCII token at all (e.g. a homoglyph the text pass did not fold): fall back
    # to the squashed form rather than declaring the series uncoverable.
    squashed = _squash(alt)
    return bool(squashed) and (squashed in cand_words or squashed in cand_ngrams)


def _series_alternatives(series: str) -> list[str]:
    if "/" in series:
        return [s.strip().upper() for s in series.split("/") if s.strip()]
    return [series.upper()]


def _series_verdict(
    target: ProductSlots, cand: ProductSlots, candidate_title: str, brand: str
) -> MatchDecision | None:
    """Series comparison implementing ADR-002 Category 2 semantics.

    * candidate covers every target series token         -> pass
    * candidate omits them (no conflicting series)       -> **BASE fallback** (RC-4)
    * candidate asserts a different sub-series / series  -> REJECT
    """
    if not target.series:
        return None

    # A candidate that is a single-branch spelling of a multi-branch anchor is
    # the *same product* -- the anchor already established identity.  Any residual
    # "series" difference at that point is prose noise (e.g. "Super Pro" absorbed
    # into the slot), not a real generation difference, so the series rule must
    # not second-guess it.
    if "/" in target.anchor and cand.anchor:
        nt, nc = _squash(target.anchor), _squash(cand.anchor)
        if (
            _is_branch_form(nt, nc)
            or _is_branch_form(_strip_lead_alpha(nt), nc)
            or _is_branch_form(nc, nt)
            or nc in _anchor_equivalents(nt, target.anchor)
        ):
            return None

    # The series slot can absorb fragments of a multi-branch anchor
    # ("13HFS / 013WDC" out of "HSU-13HFS/013WDC(G)").  Those tokens belong to
    # the anchor, not to a generation series, so they are never a series
    # requirement.  Dropping them may leave nothing behind, which correctly
    # turns the whole rule into a no-op.
    anchor_words = _comparison_words(target.anchor)
    alternatives_all = _series_alternatives(target.series)
    kept = [
        " ".join(w for w in alt.split() if _squash(w) not in anchor_words)
        for alt in alternatives_all
    ]
    required = [k for k in kept if k.strip()]
    if not required:
        return None
    target_series_label = target.series
    alternatives = required

    cand_clean = re.sub(r"\([^)]*\)", " ", clean_marketplace_noise(candidate_title))
    cand_words = _comparison_words(cand_clean)
    alternatives = _series_alternatives(target.series)

    cand_ngrams = _comparison_ngrams(cand_clean)
    matched_alt = next(
        (alt for alt in alternatives if _series_covered(alt, cand_words, cand_ngrams)), None
    )

    if matched_alt is None:
        # `clean_marketplace_noise` truncates a title at a long dash, so a vendor
        # title such as "EAF-05 Air Fryer - 4.5L Low-Fat Digital Air Fryer" loses
        # its own trailing series before we can compare.  Re-test against the raw
        # title: if the series tokens are literally present the listing *does*
        # assert the same series, and must not be rejected for omitting it.
        raw_words = _comparison_words(candidate_title)
        raw_ngrams = _comparison_ngrams(candidate_title)
        matched_alt = next(
            (alt for alt in alternatives if _series_covered(alt, raw_words, raw_ngrams)), None
        )

    if matched_alt is None and _soft_styling_optional(target, cand, brand):
        matched_alt = alternatives[0]

    if matched_alt is None:
        # RC-4: an omitted series is the *base model* case, not a hard reject --
        # unless the candidate asserts a series of its own (a real difference).
        if cand.series.strip():
            return _reject(
                f"Missing required series tokens for any alternative in "
                f"'{target_series_label}' (candidate asserts '{cand.series}')",
                target,
                cand,
            )
        return _reject(
            f"Missing required series tokens for any alternative in '{target_series_label}': "
            "market listing omitted them (base-model fallback)",
            target,
            cand,
            base=True,
            missing=target_series_label,
        )

    extra_sub = (
        _comparison_words(cand.series) & GENUINE_SUB_SERIES_TOKENS
    ) - (_comparison_words(matched_alt) & GENUINE_SUB_SERIES_TOKENS)
    if extra_sub:
        return _reject(
            f"Sub-series mismatch: candidate has extra series token(s) "
            f"{', '.join(sorted(extra_sub))} not in target '{matched_alt}'",
            target,
            cand,
        )
    return None


def _soft_styling_optional(target: ProductSlots, cand: ProductSlots, brand: str) -> bool:
    """Unique >=4-digit stems tolerate a seller dropping soft styling trim (Chrome FH)."""
    if cand.series.strip() or not target.anchor:
        return False
    stem_match = re.search(r"\d{4,}", target.anchor)
    if not stem_match:
        return False
    target_text = " ".join(
        [
            target.anchor,
            target.series,
            target.guarded_facets.tub_series or "",
            *target.residuals,
        ]
    ).upper()
    target_chars = _squash(target_text)
    extra = _squash(cand.anchor).replace(stem_match.group(0), "")
    if brand:
        extra = re.sub(rf"^{re.escape(brand[0].upper())}[A-Z]{{0,3}}", "", extra)
    return not extra or all(ch in target_chars for ch in extra)


def _capability_verdict(target: ProductSlots, cand: ProductSlots) -> MatchDecision | None:
    """Category-2 capabilities: extra -> REJECT, missing -> BASE fallback."""
    t_caps, c_caps = (
        target.guarded_facets.capabilities,
        cand.guarded_facets.capabilities,
    )
    extra = {
        c for c in (c_caps - t_caps) if not (target.anchor and c in target.anchor.upper())
    }
    if extra:
        names = ", ".join(sorted(extra))
        return _reject(
            f"Hardware capability mismatch ({names} mismatch): Candidate has extra "
            f"capability {names} not present in target",
            target,
            cand,
        )
    missing = {
        c for c in (t_caps - c_caps) if not (cand.anchor and c in cand.anchor.upper())
    }
    if missing:
        names = ", ".join(sorted(missing))
        return _reject(
            f"Hardware capability omitted ({names} mismatch): Target specifies {names} "
            "but candidate does not",
            target,
            cand,
            base=True,
            missing=names,
        )
    return None


def _best_branch_decision(
    decisions: Sequence[MatchDecision],
) -> MatchDecision:
    """Pick the strongest verdict across expanded branches (exact > base > collision)."""
    for tier in (TIER_EXACT, TIER_BASE):
        for dec in decisions:
            if dec.tier == tier:
                return dec
    for dec in decisions:
        if any(word in dec.reason for word in ("mismatch", "collision")):
            return dec
    return decisions[0]


def referee_match(
    target: ProductSlots | str, candidate_title: str, brand: str = ""
) -> MatchDecision:
    """Decide EXACT / BASE / REJECT for one marketplace listing (ADR-002).

    ``Decision = Anchor Match AND NOT(Any Guarded Facet Collision)``; a listing that
    matches the base model but omits a requested modifier is reported as a BASE
    fallback so the caller can reprice against it *and* raise a cross-check notice.
    """
    for text, is_target in ((target, True), (candidate_title, False)):
        if not isinstance(text, str):
            continue
        branches = expand_cartesian_branches(text)
        if len(branches) <= 1:
            continue
        if is_target:
            return _best_branch_decision(
                [referee_match(b, candidate_title, brand=brand) for b in branches]
            )
        return _best_branch_decision(
            [referee_match(target, b, brand=brand) for b in branches]
        )

    target_slots = extract_product_slots(target, brand=brand) if isinstance(target, str) else target
    cand_slots = extract_product_slots(candidate_title, brand=brand)
    # "(G)" in the catalog and "…UVGT3" in a listing are the same tag: fold the
    # glued spelling into the variant_tag slot before any verdict runs.
    target_slots, cand_slots = _reconcile_variant_tags(target_slots, cand_slots)

    if (verdict := _run_rules(_FACET_RULES, target_slots, cand_slots)) is not None:
        return verdict
    if (verdict := _anchor_verdict(target_slots, cand_slots, candidate_title, brand)) is not None:
        return verdict
    # A hard capacity/colour COLLISION rejects before any series-omission fallback:
    # a Silver listing must never price against a Champagne target just because it
    # also omitted the series words.  Omissions (base) still fall through.
    if (
        verdict := _run_rules(_POST_FACET_RULES, target_slots, cand_slots)
    ) is not None and not verdict.is_base_match:
        return verdict
    if (verdict := _series_verdict(target_slots, cand_slots, candidate_title, brand)) is not None:
        return verdict
    if (verdict := _capability_verdict(target_slots, cand_slots)) is not None:
        return verdict
    if (
        verdict := _run_rules(_POST_FACET_RULES, target_slots, cand_slots)
    ) is not None:
        return verdict

    matched_id = target_slots.anchor or target_slots.series or "Target"
    return MatchDecision(
        is_match=True,
        reason=f"Accepted: {matched_id} matched with zero guarded facet collisions",
        target_slots=target_slots,
        candidate_slots=cand_slots,
    )


# =============================================================================
# 10. STRICT MATCHER (legacy boolean contract used by pipeline telemetry)
# =============================================================================

_TARGET_TAG_STRIP_RE = re.compile(r"(?:T3|AAA|AA\+|AA|PRO|ULTRA|GC|GT|JT)+$", re.IGNORECASE)


def _keyword_match(expanded_title: str, target_keywords: str, brand: str = "") -> bool:
    """Strict all-keyword containment for name-only products (with T3 isolation)."""
    title_upper = expanded_title.upper()
    title_words = set(re.findall(r"[A-Z0-9]+", title_upper))
    target_tokens = [
        t for t in (_squash(tok) for tok in target_keywords.split()) if t
    ]
    target_set = set(target_tokens)

    target_brand = brand.strip()
    if not target_brand:
        words = set(re.findall(r"[A-Za-z]+", f"{expanded_title} {target_keywords}".upper()))
        target_brand = next(
            (p for p in BRAND_CAPACITY_SYSTEMS if any(w.startswith(p) for w in words)), ""
        )

    if "T3" not in target_set and "T3" in title_words:
        return False

    for kw in target_tokens:
        if kw in title_words:
            continue
        tonnage = get_capacity_tonnage(kw, target_brand)
        if tonnage and tonnage_matches_title(tonnage, title_upper):
            continue
        if reverse_tonnage_matches(kw, title_words, target_brand):
            continue
        return False
    return True


def _single_letter_suffix_collision(target_model: str, candidate_title: str) -> bool:
    """Conflicting single-letter variant suffix on the same stem (DWT-270 C vs 270 S)."""
    tokens = target_model.split()
    for i, tok in enumerate(tokens[:-1]):
        nxt = tokens[i + 1]
        m_stem = re.fullmatch(r"([A-Za-z]*)[- ]?(\d{3,})", tok.strip())
        if not (m_stem and re.fullmatch(r"[A-Za-z]", nxt)):
            continue
        letters, digits = m_stem.group(1), m_stem.group(2)
        pattern = (
            rf"(?<![A-Za-z0-9]){re.escape(letters)}[-\s]?{digits}(?!\d)"
            r"(?:[-\s]?([A-Za-z])(?![A-Za-z0-9]))?"
        )
        found = {
            m.group(1).upper()
            for m in re.finditer(pattern, candidate_title, re.IGNORECASE)
            if m.group(1)
        }
        if found and nxt.upper() not in found:
            return True
    return False


_FINISH_PAIRS: tuple[tuple[str, str], ...] = (
    (r"\b(?:GD|GLASS\s+DOOR)\b", r"\b(?:INOX|STAINLESS(?:\s+STEEL)?|S\.S)\b"),
)


def _finish_collision(target: str, candidate: str) -> bool:
    for gd, inox in _FINISH_PAIRS:
        t_gd, t_inox = bool(re.search(gd, target, re.I)), bool(re.search(inox, target, re.I))
        c_gd, c_inox = bool(re.search(gd, candidate, re.I)), bool(re.search(inox, candidate, re.I))
        if (t_gd and c_inox) or (t_inox and c_gd):
            return True
    return False


def _initialism_collision(target_tokens: list[str], expanded_title: str, norm_title: str,
                          brand: str) -> bool:
    """Dynamic initialism referee: target 'SD' rejects 'DD' / 'Double Door'."""
    acronyms = [t for t in target_tokens if len(t) == 2 and t.isalpha()]
    if not acronyms:
        return False

    cleaned = expanded_title
    if brand:
        cleaned = re.sub(rf"\b{re.escape(brand)}\b", "", cleaned, flags=re.IGNORECASE)

    words: list[str | None] = []
    for t in cleaned.split():
        if re.search(r"\d", t):
            words.append(None)  # digit-bearing tokens act as boundaries
        else:
            w = re.sub(r"[^A-Za-z]", "", t).upper()
            if w:
                words.append(w)

    for acr in acronyms:
        if acr in words or acr in norm_title:
            continue
        a1, a2 = acr[0], acr[1]
        if any(w and len(w) == 2 and w[1] == a2 and w[0] != a1 for w in words):
            return True
        for w1, w2 in zip(words, words[1:], strict=False):
            if (
                w1 and w2
                and len(w1) >= 3 and len(w2) >= 3
                and w2[0] == a2 and w1[0] != a1 and w1[0] not in ("A", "AN", "THE")
            ):
                return True
    return False


def _has_model_code(clean_target: str) -> bool:
    """Does the target contain a real SKU token (vs a pure keyword phrase)?"""
    return any(
        (len(t) >= 3 and re.search(r"\d", t) and re.search(r"[A-Za-z]", t))
        or bool(re.search(r"^\d+-\d+$", t))
        or bool(re.search(r"^\d{3,}$", t))
        for t in clean_target.split()
        if t
    )


def is_strict_model_match(scraped_title: str, target_model: str, brand: str = "") -> bool:
    """Strict boolean variant check for a scraped title against a catalog model."""
    expanded_title = expand_multivariant_titles(scraped_title)
    clean_target = join_capacity_stems(target_model.strip())

    if not _has_model_code(clean_target):
        return _keyword_match(expanded_title, clean_target, brand=brand) or referee_match(
            clean_target, expanded_title, brand=brand
        ).is_match

    norm_target, norm_title = _squash(clean_target), _squash(expanded_title)
    base_target = _TARGET_TAG_STRIP_RE.sub("", norm_target)
    base_targets = list(_anchor_equivalents(base_target))

    # Structural numeric prefix collision (18 vs 24, 100 vs 120).
    if m := re.match(r"^([0-9]+)([A-Z]+)", base_target):
        target_num, target_series = m.group(1), m.group(2)
        if not any(bt in norm_title for bt in base_targets):
            for found in re.finditer(rf"([0-9]+){re.escape(target_series)}", norm_title):
                if len(found.group(1)) == len(target_num) and found.group(1) != target_num:
                    return False

    if _finish_collision(clean_target, expanded_title):
        return False

    target_colors = get_all_color_families(clean_target)
    if target_colors:
        cand_colors = get_all_color_families(expanded_title)
        if cand_colors and not target_colors.intersection(cand_colors):
            return False

    if _single_letter_suffix_collision(clean_target, expanded_title):
        return False

    target_tokens = [_squash(t) for t in clean_target.split() if t.strip()]
    core_tokens = [
        t for t in target_tokens
        if (any(c.isdigit() for c in t) or len(t) >= 4) and not is_color_token(t)
    ] or [t for t in target_tokens if any(c.isdigit() for c in t) or len(t) >= 4]

    if _initialism_collision(target_tokens, expanded_title, norm_title, brand):
        return False

    # Pure numeric stems must carry the brand name or a brand-initial SKU prefix.
    if brand and core_tokens and core_tokens[0].isdigit():
        b_clean = brand.strip().lower()
        title_lower = expanded_title.lower()
        has_brand_name = b_clean in title_lower
        has_brand_sku = bool(
            re.search(
                rf"\b{re.escape(b_clean[0])}[a-z]{{1,3}}[- ]?{re.escape(core_tokens[0])}\b",
                title_lower,
            )
        )
        if not (has_brand_name or has_brand_sku):
            return False

    if len(core_tokens) > 1 and all(t in norm_title for t in core_tokens):
        return True
    if len(core_tokens) == 1 and core_tokens[0] in norm_title and len(core_tokens[0]) >= 3:
        return True
    if any(bt in norm_title for bt in base_targets):
        return True

    # White/default colour fallback: base without the trailing 'W' is acceptable when
    # no conflicting colour code follows the stem.
    if base_target.endswith("W") and base_target[:-1] in norm_title:
        base_no_w = base_target[:-1]
        for w in expanded_title.split():
            core = _TARGET_TAG_STRIP_RE.sub("", _squash(w))
            idx = core.find(base_no_w)
            if idx != -1:
                remainder = core[idx + len(base_no_w):]
                if remainder and remainder != "W":
                    return False
        return True

    # Technical slash suffix fallback (18HE/DC, GN-261/21): seller may drop the suffix.
    if "/" in clean_target:
        core = _TARGET_TAG_STRIP_RE.sub("", _squash(clean_target.split("/")[0].strip()))
        if core and core in norm_title:
            if m := re.match(r"^([0-9]+)([A-Z]+)", core):
                for found in re.finditer(rf"([0-9]+){re.escape(m.group(2))}", norm_title):
                    if len(found.group(1)) == len(m.group(1)) and found.group(1) != m.group(1):
                        return False
            return True

    return False
