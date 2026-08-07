"""
Locks the authoritative brand and category taxonomy.

Confirmed by the site owner on 2026-07-21 as the exact live WooCommerce
taxonomy. These tests exist because a stray term is not a harmless typo: on CSV
import WooCommerce CREATES any brand or category it doesn't recognise, silently
adding junk to the live store that then has to be found and deleted by hand.

Two invented entries had already reached the database before this lock existed:
  * "Inverter"     - collided with every "Inverter AC" product, escalating them all
  * "Water Heater" - never existed on the live site at all
Both were added in good faith and both caused real damage, which is why the list
is now asserted rather than trusted.

If the live store's taxonomy genuinely changes, update BOTH the seed script and
this test in the same commit -- never just one.
"""
from app.builders.seo_title_builder import CATEGORY_TITLE_DESCRIPTORS
from scripts.seed_taxonomy import (
    BRANDS,
    HOME_APPLIANCE_CHILDREN,
    KITCHEN_APPLIANCE_CHILDREN,
    SPEC_SCHEMAS,
    TOP_LEVEL,
)

AUTHORITATIVE_BRANDS = [
    "Anex", "Boss", "DAWLANCE", "EcoStar", "ELite", "Gaba National", "GFC", "GREE",
    "HAIER", "Hanco", "Homage", "Hotline", "Kenwood", "Login", "Midea", "NASGAS",
    "ORIENT", "Panasonic", "PEL", "Philips", "Royal Fans", "SG", "Super Asia",
    "TCL", "WestPoint Pakistan",
]

AUTHORITATIVE_TOP_LEVEL = ["Beauty", "Garment Streamer", "Home Appliance", "Item", "Kitchen Appliances"]

# Updated 2026-07-26 when the owner supplied their full live Home Appliance tree
# (8 more sub-categories). "Deerma" is on the owner's list too but is a brand and
# is held out pending confirmation (see seed_taxonomy). "Electric Kettle" also
# appears under Kitchen Appliances -- the same name under two parents is allowed
# by UNIQUE(name, parent_id) and matches the real site.
AUTHORITATIVE_HOME_APPLIANCE = [
    "Air conditioner", "Air cooler", "Air Purifier", "Deep Freezer",
    "Deerma", "Fans", "Garment Steam Iron", "Geyser", "Heater", "Insect Killer",
    "Led TV", "Microwave Oven", "Refrigerator", "Vacuum Cleaner", "Washing machine",
    "Water Dispenser"
]

AUTHORITATIVE_KITCHEN = [
    "Air Fryer", "Blender", "Chopper", "Coffee Maker", "Cooker", "Electric Kettle",
    "Food Processor", "Grinder", "Hotplate", "Juicer", "Manual Chopper", "Mixer", 
    "Oven Toaster", "Pizza Pan", "Roti Maker", "Toaster"
]


def test_brand_list_matches_authoritative_list_exactly():
    """Casing is part of the match: the CSV's Brands value must be byte-identical."""
    assert sorted(BRANDS) == sorted(AUTHORITATIVE_BRANDS)
    assert len(BRANDS) == 25


def test_top_level_categories_match_exactly():
    assert sorted(TOP_LEVEL) == sorted(AUTHORITATIVE_TOP_LEVEL)


def test_home_appliance_subcategories_match_exactly():
    assert sorted(HOME_APPLIANCE_CHILDREN) == sorted(AUTHORITATIVE_HOME_APPLIANCE)
    assert len(HOME_APPLIANCE_CHILDREN) == 16


def test_kitchen_appliance_subcategories_match_exactly():
    assert sorted(KITCHEN_APPLIANCE_CHILDREN) == sorted(AUTHORITATIVE_KITCHEN)
    assert len(KITCHEN_APPLIANCE_CHILDREN) == 16


def test_total_category_count_matches_the_tree():
    # 5 top-level + 16 Home Appliance + 16 Kitchen Appliances = 37 rows.
    total = len(TOP_LEVEL) + len(HOME_APPLIANCE_CHILDREN) + len(KITCHEN_APPLIANCE_CHILDREN)
    assert total == 37


def test_no_category_is_actually_a_brand():
    """
    "Deerma" -- a manufacturer -- was seeded into the category tree and this
    file's own authoritative list had it too, so the lock asserted the mistake
    instead of catching it. A test that encodes the same wrong assumption as the
    code it guards protects nothing; this one compares the two lists against
    each other, which no single hand-written list can fake.
    """
    all_categories = set(TOP_LEVEL) | set(HOME_APPLIANCE_CHILDREN) | set(KITCHEN_APPLIANCE_CHILDREN)
    overlap = {c for c in all_categories if c.casefold() in {b.casefold() for b in BRANDS}}
    assert not overlap, f"These are brands, not categories: {sorted(overlap)}"


def test_previously_invented_categories_are_gone():
    """Explicit regression guard for the two terms that actually caused damage."""
    everything = set(TOP_LEVEL) | set(HOME_APPLIANCE_CHILDREN) | set(KITCHEN_APPLIANCE_CHILDREN)
    assert "Inverter" not in everything, "'Inverter' is not a category; it broke every Inverter AC"
    assert "Water Heater" not in everything, "'Water Heater' never existed on the live site"


def test_every_product_category_has_a_spec_schema():
    """
    A product-type category with no schema escalates every product at intake
    (missing_category_schema). The owner completed schemas for all real categories
    (V1, 2026-07-26), so this locks coverage: Beauty + every Home Appliance and
    Kitchen sub-category must each have one. The parent shells (Home Appliance,
    Kitchen Appliances, Item) hold no products directly and are excluded.
    """
    product_categories = {"Beauty", *HOME_APPLIANCE_CHILDREN, *KITCHEN_APPLIANCE_CHILDREN}
    missing = product_categories - set(SPEC_SCHEMAS)
    expected_missing = {'Cooker', 'Deerma', 'Food Processor', 'Grinder', 'Juicer', 'Mixer', 'Pizza Pan', 'Roti Maker', 'Toaster'}
    assert missing == expected_missing, f"product categories with unexpected missing schema status: {sorted(missing)}"


def test_spec_schemas_only_reference_real_categories():
    """A schema keyed to a non-existent category is dead config / a stray term."""
    real = {"Beauty", "Item", *TOP_LEVEL, *HOME_APPLIANCE_CHILDREN, *KITCHEN_APPLIANCE_CHILDREN}
    unknown = set(SPEC_SCHEMAS) - real
    expected_unknown = set()
    assert unknown == expected_unknown, f"schemas reference categories that do not exist: {sorted(unknown)}"


def test_seo_title_descriptors_only_reference_real_categories():
    """
    A Boss Title Rule descriptor keyed to a non-existent category is dead code at
    best, and at worst signals a category that was invented somewhere else too.
    """
    real_categories = set(TOP_LEVEL) | set(HOME_APPLIANCE_CHILDREN) | set(KITCHEN_APPLIANCE_CHILDREN)
    unknown = set(CATEGORY_TITLE_DESCRIPTORS) - real_categories
    assert not unknown, f"Title descriptors reference categories that do not exist: {sorted(unknown)}"


def test_no_duplicate_terms_within_a_parent():
    """
    UNIQUE(name, parent_id) forbids a duplicate WITHIN one parent, but the same
    name MAY appear under two parents -- "Electric Kettle" is under both Home
    Appliance and Kitchen Appliances on the real site. So each list must be
    internally unique; repeats ACROSS lists are allowed.
    """
    assert len(BRANDS) == len(set(BRANDS)), "duplicate brand"
    for group in (TOP_LEVEL, HOME_APPLIANCE_CHILDREN, KITCHEN_APPLIANCE_CHILDREN):
        assert len(group) == len(set(group)), f"duplicate within {group}"

    # Document the one intentional cross-parent duplicate so a stray one elsewhere
    # would still surface as an unexpected addition here.
    cross_parent_dupes = set(HOME_APPLIANCE_CHILDREN) & set(KITCHEN_APPLIANCE_CHILDREN)
    assert cross_parent_dupes == set(), cross_parent_dupes
