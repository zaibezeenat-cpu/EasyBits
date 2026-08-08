"""
Category resolution measured against the operator's real 296-product Anex sheet.

WHY THIS EXISTS
---------------
Running the real sheet through _build_inputs showed 134 of 296 products failing
deterministic category resolution. Splitting them apart gave three very
different problems, and only one of them is a code problem:

  32   AMBIGUOUS  -- multi-function products ("Blender, Grinder 2 in 1") that
                    genuinely match several unrelated categories. infer_category
                    returns None on purpose here; guessing files the product
                    under the wrong breadcrumb on the live store. These need the
                    sheet's Category column.
  102  NO MATCH   -- of which ~50 belong to a category that ALREADY EXISTS and
                    simply had no alias, and the rest need categories the store
                    does not have yet (Sandwich Maker, Kitchen Robot, ...).

This file covers that ~50. Each alias below maps real product titles onto a
category already in the taxonomy, so the products resolve deterministically --
free, reproducible, and with no LLM guess -- instead of falling through to
llm_pick_category, which sees only the title anyway.

Every fixture is a VERBATIM title from tests/files/anex_total_products_details.csv,
including the sheet's own misspelling "Straightner", because that is what the
matcher will actually be handed.
"""
import pytest

from app.builders.input_adapter import infer_category
from scripts.seed_taxonomy import (
    HOME_APPLIANCE_CHILDREN,
    KITCHEN_APPLIANCE_CHILDREN,
    TOP_LEVEL,
)

REAL_CATEGORIES = list(TOP_LEVEL) + list(HOME_APPLIANCE_CHILDREN) + list(KITCHEN_APPLIANCE_CHILDREN)


def _resolve(title: str) -> str | None:
    return infer_category(title, REAL_CATEGORIES)


# --- Beauty: 30 products, all personal-care, category already exists ---------

@pytest.mark.parametrize("title", [
    "Hair Dryer (1600 W)",
    "Hair Dryer With Ionic 2200 Watts",
    "Hair Straightner",                     # the sheet's own spelling
    "Hair Straightener & Curler",
    "Hair Straightner, Curler, Crimper",
    "Curl & Straight Styler",
    "Trimmer",
    "Hair Trimmer, Nose Trimmer, Shaver",
    "Hair Curler",
    "Facial Steamer",
])
def test_personal_care_products_resolve_to_beauty(title: str):
    assert _resolve(title) == "Beauty"


# --- Garment Steam Iron: 12 products. The category name needs all three words,
#     but every real title says only "Dry Iron" or "Steam Iron". ---------------

@pytest.mark.parametrize("title", [
    "Dry Iron",
    "Dry Iron With Spray",
    "Dry Iron (1000 W)",
    "Middle Weight Iron",
    "Steam Iron (2200 W)",
    "Steam Iron",
])
def test_irons_resolve_to_the_garment_steam_iron_category(title: str):
    assert _resolve(title) == "Garment Steam Iron"


# --- Garment Streamer: the live store spells it "Streamer", the products all
#     say "Steamer". One letter, 6 products. ---------------------------------

@pytest.mark.parametrize("title", [
    "Garment Steamer",
    "Handy Garment Steamer 2100W",
    "Handy Garment Steamer 1600-1800W",
])
def test_garment_steamers_resolve_despite_the_streamer_spelling(title: str):
    assert _resolve(title) == "Garment Streamer"


def test_a_facial_steamer_is_beauty_not_a_garment_steamer():
    """
    The trap in this group. A bare "steamer" alias would file AG-7018 Facial
    Steamer under garment care. The alias is anchored to "garment".
    """
    assert _resolve("Facial Steamer") == "Beauty"


# --- The new aliases must not disturb anything that already worked -----------

@pytest.mark.parametrize("title,expected", [
    ("Handy Pull Chopper", "Hand Chopper"),
    ("Hand Blender, 400 W", "Hand Blender"),
    ("Electric Kettle 1.8 Ltr", "Electric Kettle"),
    ("Air Fryer 5.5 Ltr", "Air Fryer"),
    ("Vacuum Cleaner 1500 W", "Vacuum Cleaner"),
    ("Insect Killer", "Insect Killer"),
    ("Oven Toaster 45 Ltr", "Oven Toaster"),
])
def test_previously_resolving_products_are_unaffected(title: str, expected: str):
    assert _resolve(title) == expected


def test_genuinely_ambiguous_products_still_refuse_to_guess():
    """
    Unchanged by design. A multi-function product matches several unrelated
    categories and the operator must choose -- a wrong breadcrumb files it in
    the wrong place on the live store, which is harder to spot and undo than a
    row that stops for review.
    """
    assert _resolve("Blender, Grinder 2 in 1") is None
    assert _resolve("Juicer, Blender, Grinder (600 W)") is None


def test_the_sheet_reaches_the_expected_coverage():
    """
    The headline number, measured on the real file rather than asserted from
    memory. Guards against an alias being deleted and nobody noticing until a
    live run.
    """
    import csv
    from pathlib import Path

    sheet = Path(__file__).resolve().parents[1] / "files" / "anex_total_products_details.csv"
    rows = [r for r in csv.DictReader(sheet.open(encoding="utf-8-sig")) if (r.get("Name") or "").strip()]
    resolved = sum(1 for r in rows if _resolve(r["Name"].strip()))

    assert resolved >= 213, (
        f"only {resolved}/{len(rows)} Anex products resolve deterministically; "
        f"213 is the floor after the Beauty / iron / garment-steamer aliases"
    )
