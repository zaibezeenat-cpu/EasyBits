"""
Tests for the sheet input adapter.

The price tests guard a job-risk path: getting the regular/sale roles backwards
publishes a price INCREASE to customers as a discount. All fixtures below are
real rows from the user's actual input sheet and their corresponding real CSV
export, so these assert against ground truth rather than invented examples.
"""
import pytest
from decimal import Decimal

from app.builders.input_adapter import (
    assign_prices,
    build_sku,
    detect_template,
    extract_sku,
    infer_category,
    match_brand,
    normalise_warranty,
    parse_sheet_row,
)

# Mirrors the real seeded taxonomy (backend/scripts/seed_taxonomy.py).
REAL_BRANDS = [
    "Anex", "Boss", "DAWLANCE", "EcoStar", "ELite", "Gaba National", "GFC", "GREE",
    "HAIER", "Hanco", "Homage", "Hotline", "Kenwood", "Login", "Midea", "NASGAS",
    "ORIENT", "Panasonic", "PEL", "Philips", "Royal Fans", "SG", "Super Asia",
    "TCL", "WestPoint Pakistan",
]
REAL_CATEGORIES = [
    "Air conditioner", "Air cooler", "Air Purifier", "Deep Freezer", "Fans",
    "Geyser", "Heater", "Microwave Oven", "Refrigerator", "Vacuum Cleaner",
    "Washing machine", "Water Dispenser", "Water Heater", "Air Fryer", "Blender",
    "Coffee Maker", "Electric Kettle", "Hotplate", "Oven Toaster", "Led TV",
    "Chopper"
]

# child -> parent, mirroring the seeded two-level category tree.
REAL_CATEGORY_PARENTS = {
    "Air conditioner": "Home Appliance",
    "Air cooler": "Home Appliance",
    "Air Purifier": "Home Appliance",
    "Deep Freezer": "Home Appliance",
    "Fans": "Home Appliance",
    "Geyser": "Home Appliance",
    "Heater": "Home Appliance",
    "Microwave Oven": "Home Appliance",
    "Refrigerator": "Home Appliance",
    "Vacuum Cleaner": "Home Appliance",
    "Washing machine": "Home Appliance",
    "Water Dispenser": "Home Appliance",
    "Water Heater": "Home Appliance",
    "Led TV": "Home Appliance",
    "Air Fryer": "Kitchen Appliances",
    "Blender": "Kitchen Appliances",
    "Coffee Maker": "Kitchen Appliances",
    "Electric Kettle": "Kitchen Appliances",
    "Hotplate": "Kitchen Appliances",
    "Oven Toaster": "Kitchen Appliances",
}


# --- Price assignment -------------------------------------------------------

def test_legacy_prices_match_real_csv_export():
    """Legacy: use price_a and price_b."""
    regular, sale = assign_prices(price_a=Decimal("139999"), price_b=Decimal("150000"))
    assert regular == Decimal("150000")
    assert sale == Decimal("139999")

def test_legacy_sale_is_always_below_regular_regardless_of_argument_order():
    for a, b in [
        (Decimal("139999"), Decimal("150000")),
        (Decimal("150000"), Decimal("139999")),
    ]:
        regular, sale = assign_prices(price_a=a, price_b=b)
        assert sale is not None
        assert sale < regular

def test_sale_price_without_regular_adds_markup():
    regular, sale = assign_prices(sale_price=Decimal("1000"))
    assert regular == Decimal("1100.00")
    assert sale == Decimal("1000")

def test_sale_and_regular_price_provided():
    regular, sale = assign_prices(sale_price=Decimal("1000"), regular_price=Decimal("1200"))
    assert regular == Decimal("1200")
    assert sale == Decimal("1000")

def test_sale_and_regular_price_swapped():
    regular, sale = assign_prices(sale_price=Decimal("1200"), regular_price=Decimal("1000"))
    assert regular == Decimal("1200")
    assert sale == Decimal("1000")

def test_equal_prices_mean_no_discount():
    regular, sale = assign_prices(price_a=Decimal("99999"), price_b=Decimal("99999"))
    assert regular == Decimal("99999")
    assert sale is None

def test_non_positive_price_is_rejected():
    with pytest.raises(ValueError):
        assign_prices(price_a=Decimal("0"), price_b=Decimal("150000"))
    with pytest.raises(ValueError):
        assign_prices(sale_price=Decimal("-5"))


# --- SKU extraction ---------------------------------------------------------

@pytest.mark.parametrize(
    "product_name,expected_sku",
    [
        (
            "Kenwood KLU-12B03S 1.0 Ton Luxury Ultra Inverter AC – T3 Cooling, WiFi, Energy Saving",
            "KLU-12B03S",
        ),
        (
            "Midea 18HRFN8 Breezeless 1.5 Ton Inverter AC | R32 T3 | Heat & Cool | Official Warranty",
            "18HRFN8",
        ),
        (
            "Midea 24HRDN1 2 TON T3 Xtreme Eco Inverter Air Conditioner",
            "24HRDN1",
        ),
        (
            "Midea 2 Ton MSEZ2C-24HRFN1 Xtreme Plus Inverter AC (2026 Latest Model)",
            "MSEZ2C-24HRFN1",
        ),
    ],
)
def test_extract_sku_from_real_product_names(product_name: str, expected_sku: str):
    assert extract_sku(product_name) == expected_sku


def test_extract_sku_ignores_short_spec_tokens():
    """
    'R32' (refrigerant) and 'T3' (compressor rating) mix letters and digits but
    are specs, not identifiers. The real model number must win.
    """
    assert extract_sku("Midea R32 T3 18HRFN8 Inverter AC") == "18HRFN8"


def test_extract_sku_ignores_capacity_tokens():
    """'100L' and '1500W' clear the length floor but are capacities, not SKUs."""
    assert extract_sku("Dawlance 100L 1500W DW-131HP Microwave Oven") == "DW-131HP"


def test_extract_sku_returns_none_when_no_model_number_present():
    """Must return None so the caller escalates -- never invent a SKU."""
    assert extract_sku("Dawlance Microwave Oven") is None
    assert extract_sku("") is None


# --- SKU uniqueness ---------------------------------------------------------

def test_sku_appends_colour_for_uniqueness():
    """
    The same model ships in several colours, so a bare model number is not
    unique. A duplicate SKU makes WooCommerce OVERWRITE the live product.
    """
    assert build_sku("DBD-1035", color="Glass") == "DBD-1035-GLASS"
    assert build_sku("YL-2037S-B", color="Black") == "YL-2037S-B-BLACK"


def test_sku_falls_back_to_variant_when_no_colour():
    assert build_sku("DWOT-2515", variant="25L") == "DWOT-2515-25L"


def test_sku_prefers_colour_over_variant():
    assert build_sku("DBD-1035", color="Silver", variant="30L") == "DBD-1035-SILVER"


def test_unknown_qualifier_is_never_guessed_into_the_sku():
    """
    A wrong qualifier yields an SKU matching nothing (recoverable); a wrongly
    SHARED SKU overwrites a live listing (not recoverable). So UNKNOWN is
    dropped rather than invented.
    """
    assert build_sku("DWHJ-8002", color="UNKNOWN") == "DWHJ-8002"
    assert build_sku("DWHJ-8002", color="") == "DWHJ-8002"
    assert build_sku("DWHJ-8002") == "DWHJ-8002"


def test_sku_does_not_duplicate_a_qualifier_already_in_the_model():
    assert build_sku("DBD-1035-GLASS", color="Glass") == "DBD-1035-GLASS"


def test_sku_qualifier_is_slugified():
    """Spaces and punctuation would break the SKU format."""
    assert build_sku("ABC-1", color="Rose Gold") == "ABC-1-ROSE-GOLD"


def test_sku_requires_a_model_number():
    assert build_sku("") is None
    assert build_sku("   ") is None


# --- Template selection -----------------------------------------------------

def test_detect_template_a_from_real_no_images_status():
    status = "no description images here so used no images product description template"
    assert detect_template(status) == "A"


def test_detect_template_b_from_real_images_found_status():
    status = (
        "Done with description images FOUND, SO MAKE A DESCRIPTION WITH IMAGE ONE "
        "JUST LIKE BEFORE."
    )
    assert detect_template(status) == "B"


def test_detect_template_returns_none_when_ambiguous():
    """
    An unclear status must NOT default to 'A' -- that would emit three empty
    <img src=""> slots. None hands the decision to image_fallback_node.
    """
    assert detect_template("Done") is None
    assert detect_template(None) is None
    assert detect_template("") is None


# --- Warranty ---------------------------------------------------------------

def test_warranty_wording_is_preserved_exactly():
    """
    Wording must survive untouched: the same phrase has to match across all four
    warranty locations, so rewriting it here would break that consistency check.
    """
    raw = "10 Years Compressor Warranty; 5 Years All Parts Warranty"
    assert normalise_warranty(raw) == raw


def test_warranty_whitespace_is_normalised_but_words_are_not():
    assert (
        normalise_warranty("  10 Years   Compressor Warranty;\n5 Years All Parts Warranty  ")
        == "10 Years Compressor Warranty; 5 Years All Parts Warranty"
    )


def test_empty_warranty_returns_none():
    assert normalise_warranty(None) is None
    assert normalise_warranty("   ") is None


# --- Brand matching ---------------------------------------------------------

def test_match_brand_returns_canonical_taxonomy_casing_not_sheet_casing():
    """
    The sheet writes "Kenwood"/"Midea"; the CSV must carry whatever the live
    taxonomy stores. This is what satisfies the Brand Casing Lock.
    """
    assert match_brand("Kenwood KLU-12B03S 1 Ton Inverter AC", REAL_BRANDS) == "Kenwood"
    assert match_brand("Midea 18HRFN8 Breezeless Inverter AC", REAL_BRANDS) == "Midea"


def test_match_brand_normalises_lowercase_input_to_stored_uppercase():
    """A row typed as 'dawlance' must still export as 'DAWLANCE'."""
    assert match_brand("dawlance DW-131HP Microwave Oven", REAL_BRANDS) == "DAWLANCE"


def test_match_brand_prefers_longest_match():
    """'Gaba National' must not be shadowed by a shorter partial match."""
    assert match_brand("Gaba National GN-1234 Blender", REAL_BRANDS) == "Gaba National"


def test_match_brand_returns_none_for_unknown_brand():
    assert match_brand("Samsung SM-9000 Inverter AC", REAL_BRANDS) is None


# --- Category inference -----------------------------------------------------

def test_infer_category_from_real_product_names():
    assert infer_category("Kenwood KLU-12B03S 1 Ton Inverter AC", REAL_CATEGORIES) == "Air conditioner"
    assert infer_category("Dawlance DW-131HP Microwave Oven", REAL_CATEGORIES) == "Microwave Oven"
    assert infer_category("Anex AG-04 Potato Cutter", REAL_CATEGORIES + ["Manual Chopper"]) == "Manual Chopper"
    assert infer_category("Anex AG-01 Handy Pull Chopper", REAL_CATEGORIES + ["Manual Chopper"]) == "Manual Chopper"
    assert infer_category("WestPoint Meat Chopper", REAL_CATEGORIES + ["Manual Chopper"]) == "Chopper"


def test_inverter_products_resolve_to_their_appliance_category():
    """
    "Inverter" describes the compressor, not the product type. These must land
    on the appliance category.
    """
    assert infer_category("Kenwood KLU-12B03S 1 Ton Inverter AC", REAL_CATEGORIES) == "Air conditioner"
    assert infer_category("Midea 24HRDN1 2 TON Inverter Air Conditioner", REAL_CATEGORIES) == "Air conditioner"
    assert infer_category("Haier HRF-398 Inverter Refrigerator", REAL_CATEGORIES) == "Refrigerator"


def test_adjective_like_category_can_be_excluded_when_user_creates_one():
    """
    Mechanism test, not a claim about the real taxonomy (the user owns that).
    If a category whose name is also a common adjective is ever created, it
    would otherwise match every product mentioning the word and make them all
    ambiguous. An exclusion rule resolves it; without one, the guard correctly
    escalates rather than guessing.
    """
    categories = ["Air conditioner", "Inverter"]
    name = "Kenwood KLU-12B03S 1 Ton Inverter AC"

    # No exclusion configured -> genuinely ambiguous -> escalate, never guess.
    assert infer_category(name, categories, category_exclusions={}) is None

    # With an exclusion, the appliance category wins.
    assert infer_category(
        name, categories,
        category_exclusions={"inverter": [r"\bAC\b", r"\bair\s*conditioner\b"]},
    ) == "Air conditioner"


def test_infer_category_returns_none_when_ambiguous():
    """
    A name matching two distinct categories must escalate, not pick one -- a
    wrong category files the product in the wrong place on the live store.
    """
    assert infer_category("Air cooler and air conditioner combo", REAL_CATEGORIES) is None


def test_infer_category_returns_none_when_unrecognised():
    assert infer_category("Kenwood KLU-12B03S Mystery Device", REAL_CATEGORIES) is None


def test_infer_category_restricted_to_live_taxonomy():
    """A category we can pattern-match but that isn't seeded must not be returned."""
    assert infer_category("Dawlance DW-131HP Microwave Oven", ["Air conditioner"]) is None


def test_new_category_added_in_frontend_works_with_no_code_change():
    """
    Category inference must stay DYNAMIC: a category the user adds through the
    Taxonomy Manager is matched by its own name immediately, with no entry in
    any hardcoded map and no redeploy.
    """
    user_added = REAL_CATEGORIES + ["Chest Freezer", "Rice Cooker"]
    assert infer_category("Homage HRC-2200 Rice Cooker", user_added) == "Rice Cooker"


def test_category_aliases_can_be_supplied_externally():
    """
    Aliases are overridable so they can move to a DB column later without
    touching this module.
    """
    assert infer_category("Kenwood XYZ-1 Cooling Box", ["Air conditioner"]) is None
    assert (
        infer_category(
            "Kenwood XYZ-1 Cooling Box",
            ["Air conditioner"],
            category_aliases={"air conditioner": [r"\bcooling\s*box\b"]},
        )
        == "Air conditioner"
    )


# --- Full row ---------------------------------------------------------------

def test_parse_real_sheet_row_13_end_to_end():
    row = parse_sheet_row(
        product_name="Kenwood KLU-12B03S 1.0 Ton Luxury Ultra Inverter AC – T3 Cooling, WiFi, Energy Saving",
        price_a=Decimal("139999"),
        price_b=Decimal("150000"),
        warranty_text="10 Years Compressor Warranty; 5 Years All Parts Warranty",
        status_text="no description images here so used no images product description template",
        known_brands=REAL_BRANDS,
        known_categories=REAL_CATEGORIES,
    )
    assert row.sku == "KLU-12B03S"
    assert row.brand_name == "Kenwood"
    assert row.category_name == "Air conditioner"
    assert row.regular_price == Decimal("150000")
    assert row.sale_price == Decimal("139999")
    assert row.sale_price < row.regular_price
    assert row.warranty_phrase == "10 Years Compressor Warranty; 5 Years All Parts Warranty"
    assert row.template_choice == "A"
    assert row.missing_required() == []


def test_parse_real_sheet_row_14_end_to_end():
    row = parse_sheet_row(
        product_name="Midea 18HRFN8 Breezeless 1.5 Ton Inverter AC | R32 T3 | Heat & Cool | Official Warranty",
        price_a=Decimal("199999"),
        price_b=Decimal("220000"),
        warranty_text="10 years compressor warranty; 2 years parts warranty",
        status_text="Done with description images FOUND, SO MAKE A DESCRIPTION WITH IMAGE ONE",
        known_brands=REAL_BRANDS,
        known_categories=REAL_CATEGORIES,
    )
    assert row.sku == "18HRFN8"
    assert row.brand_name == "Midea"
    assert row.category_name == "Air conditioner"
    assert row.regular_price == Decimal("220000")
    assert row.sale_price == Decimal("199999")
    assert row.warranty_phrase == "10 years compressor warranty; 2 years parts warranty"
    assert row.template_choice == "B"
    assert row.missing_required() == []


def test_all_four_real_sheet_rows_produce_sale_below_regular():
    """
    The full sample the user provided. This is the regression guard for the
    price-swap bug across every real row at once.
    """
    real_rows = [
        ("Kenwood KLU-12B03S 1.0 Ton Luxury Ultra Inverter AC", Decimal("139999"), Decimal("150000")),
        ("Midea 18HRFN8 Breezeless 1.5 Ton Inverter AC", Decimal("199999"), Decimal("220000")),
        ("Midea 24HRDN1 2 TON T3 Xtreme Eco Inverter Air Conditioner", Decimal("229999"), Decimal("250000")),
        ("Midea 2 Ton MSEZ2C-24HRFN1 Xtreme Plus Inverter AC", Decimal("249999"), Decimal("265000")),
    ]
    for name, price_a, price_b in real_rows:
        row = parse_sheet_row(
            product_name=name,
            price_a=price_a,
            price_b=price_b,
            known_brands=REAL_BRANDS,
            known_categories=REAL_CATEGORIES,
        )
        assert row.sale_price is not None
        assert row.sale_price < row.regular_price, f"{name}: sale must be below regular"
        assert row.sku is not None, f"{name}: SKU must be extracted"
        assert row.brand_name is not None, f"{name}: brand must resolve"
        assert row.category_name == "Air conditioner", f"{name}: category must resolve"


def test_category_path_is_parent_then_subcategory():
    """
    Categories are a two-level tree. WooCommerce imports the breadcrumb
    "Parent > Subcategory"; the bare child name is rejected by csv_assembler.
    """
    row = parse_sheet_row(
        product_name="Kenwood KLU-12B03S 1 Ton Inverter AC",
        price_a=Decimal("139999"),
        price_b=Decimal("150000"),
        known_brands=REAL_BRANDS,
        known_categories=REAL_CATEGORIES,
        category_parents=REAL_CATEGORY_PARENTS,
    )
    assert row.category_name == "Air conditioner"
    assert row.category_parent == "Home Appliance"
    assert row.category_path == "Home Appliance > Air conditioner"


def test_category_path_uses_the_real_parent_not_a_fixed_one():
    """Kitchen items must not be filed under Home Appliance."""
    row = parse_sheet_row(
        product_name="Anex AG-1234 Air Fryer",
        price_a=Decimal("9999"),
        price_b=Decimal("12999"),
        known_brands=REAL_BRANDS,
        known_categories=REAL_CATEGORIES,
        category_parents=REAL_CATEGORY_PARENTS,
    )
    assert row.category_path == "Kitchen Appliances > Air Fryer"


def test_category_path_falls_back_to_bare_name_for_top_level_category():
    row = parse_sheet_row(
        product_name="Some Beauty Item",
        price_a=Decimal("100"),
        price_b=Decimal("200"),
        known_categories=["Beauty"],
        category_parents={},
    )
    assert row.category_path == "Beauty"


def test_missing_required_reports_precise_reasons():
    """Unresolvable fields must be named individually so Manual Review is actionable."""
    row = parse_sheet_row(
        product_name="Samsung Mystery Appliance",
        price_a=Decimal("1000"),
        price_b=Decimal("2000"),
        known_brands=REAL_BRANDS,
        known_categories=REAL_CATEGORIES,
    )
    missing = row.missing_required()
    assert any("sku" in m for m in missing)
    assert any("brand" in m for m in missing)
    assert any("category" in m for m in missing)
