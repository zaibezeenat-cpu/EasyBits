"""
Tests for the Boss Rule product-title builder.

    [Brand] [Capacity] [SKU] [Full Product Type] - [Feature 1], [Feature 2]

The two rules that matter most: the product type is never abbreviated, and a
feature is never added unless it was verified against that specific SKU -- the
title is the most visible place a wrong specification can appear.
"""
from app.builders.name_builder import (
    MAX_NAME_LENGTH,
    build_name,
    contains_forbidden_abbreviation,
    expand_abbreviation,
)


def test_basic_formula():
    # Updated Boss Rule (2026-07-22): model comes before capacity.
    name = build_name("Dawlance", "1.5 Ton", "9199-B", "Air Conditioner")
    assert name == "Dawlance 9199-B 1.5 Ton Air Conditioner"


def test_new_boss_rule_reference_title():
    """
    The exact example the owner gave for the updated rule:
        [Brand] [Model] [Capacity] [Series/Features...] [Full Product Type]
    """
    name = build_name(
        "Haier", "10 Cu Ft", "HRF-246 EPR", "Refrigerator",
        series="LVS E-Star",
        features=["Black Glass Door", "Non Inverter"],
    )
    assert name == "Haier HRF-246 EPR 10 Cu Ft LVS E-Star Black Glass Door Non Inverter Refrigerator"


def test_model_comes_immediately_after_brand():
    name = build_name("Dawlance", "1.5 Ton", "9199-B", "Air Conditioner")
    parts = name.split()
    assert parts[0] == "Dawlance"
    assert parts[1] == "9199-B", "model must lead, before the capacity"


def test_capacity_is_normalised():
    assert build_name("Haier", "1.0 Ton", "H-1", "Refrigerator") == "Haier H-1 1 Ton Refrigerator"
    assert build_name("PEL", "20.0 Liters", "P-20", "Microwave Oven") == "PEL P-20 20L Microwave Oven"


def test_whole_number_tonnage_drops_the_decimal_but_fractions_are_kept():
    """
    Boss Rule: "1 Ton", never "1.0 Ton". Real fractions like 1.5 are meaningful
    capacity values and must survive untouched.
    """
    whole = {"1.0 Ton": "1 Ton", "1.00 Ton": "1 Ton", "2.0 Ton": "2 Ton", "1.0Ton": "1 Ton"}
    for raw, expected in whole.items():
        name = build_name("Midea", raw, "M-1", "Air Conditioner")
        assert name == f"Midea M-1 {expected} Air Conditioner", f"{raw} should render as {expected}"

    for fraction in ("1.5 Ton", "2.5 Ton", "0.75 Ton"):
        name = build_name("Midea", fraction, "M-1", "Air Conditioner")
        assert fraction in name, f"{fraction} must be preserved exactly"


def test_verified_features_sit_before_the_product_type():
    """
    The full product type always comes LAST, so the title ends on the term
    people search. Features flow into it rather than trailing after a dash.
    """
    name = build_name("Haier", "10 Cu Ft", "HRF-246", "Refrigerator",
                      features=["Inverter", "Direct Cool"])
    assert name == "Haier HRF-246 10 Cu Ft Inverter Direct Cool Refrigerator"


def test_series_sits_between_capacity_and_features():
    name = build_name("Kenwood", "1.0 Ton", "KLU-12B03S", "Air Conditioner",
                      series="Luxury Ultra", features=["Inverter Split"])
    assert name == "Kenwood KLU-12B03S 1 Ton Luxury Ultra Inverter Split Air Conditioner"


def test_series_survives_when_features_are_dropped_for_length():
    """
    The series is a proper noun customers search by, so it outranks generic
    feature words when the name must be shortened.
    """
    name = build_name("Kenwood", "1.5 Ton", "KLU-VERY-LONG-MODEL-12B03S",
                      "Air Conditioner", series="Luxury Ultra",
                      features=["Inverter Split", "T3 Compressor", "WiFi"])
    assert "Luxury Ultra" in name
    assert name.endswith("Air Conditioner")


def test_product_type_is_never_abbreviated():
    """
    "AC" and "Air Conditioner" are different keyword phrases to Rank Math, and
    the previous builder silently abbreviated to fit a 44-character cap.
    """
    name = build_name("Dawlance", "1.5 Ton", "MEGA-INVERTER-PRO", "Air Conditioner")
    assert "Air Conditioner" in name
    assert not name.endswith(" AC")


def test_base_name_is_never_truncated_even_when_long():
    """
    A truncated SKU makes the product unidentifiable. The previous builder cut
    the string and appended "..." -- worse than a slightly long name.
    """
    name = build_name("Dawlance", "1.5 Ton",
                      "VERY-LONG-MODEL-NUMBER-THAT-EXCEEDS-EVERYTHING", "Air Conditioner")
    assert not name.endswith("...")
    assert "VERY-LONG-MODEL-NUMBER-THAT-EXCEEDS-EVERYTHING" in name
    assert "Air Conditioner" in name


def test_features_are_dropped_before_the_name_overflows():
    """A missing feature costs less than an over-long name."""
    name = build_name("Dawlance", "1.5 Ton", "DW-INVERTER-9199-B", "Air Conditioner",
                      features=["Heat & Cool Tropical Operation Mode",
                                "T3 Tropical Rotary Compressor System",
                                "Wi-Fi Smart Remote Control"])
    assert len(name) <= MAX_NAME_LENGTH
    # Identity + type are never dropped; the type still closes the title.
    assert name.startswith("Dawlance DW-INVERTER-9199-B 1.5 Ton")
    assert name.endswith("Air Conditioner")


def test_no_features_yields_the_bare_formula():
    name = build_name("Midea", "1 Ton", "12HRDN1", "Air Conditioner", features=[])
    assert name == "Midea 12HRDN1 1 Ton Air Conditioner"


def test_blank_features_are_ignored():
    """An empty extraction value must not produce a dangling ' - ' separator."""
    name = build_name("Midea", "1 Ton", "12HRDN1", "Air Conditioner", features=["", "   "])
    assert name == "Midea 12HRDN1 1 Ton Air Conditioner"
    assert " - " not in name


def test_missing_capacity_does_not_leave_a_double_space():
    name = build_name("Anex", "", "AG-1234", "Blender")
    assert name == "Anex AG-1234 Blender"
    assert "  " not in name


def test_abbreviation_expansion_helper():
    assert expand_abbreviation("AC") == "Air Conditioner"
    assert expand_abbreviation("fridge") == "Refrigerator"
    # Unknown types pass through untouched rather than being guessed at.
    assert expand_abbreviation("Air Purifier") == "Air Purifier"


def test_forbidden_abbreviation_detection():
    assert contains_forbidden_abbreviation("Kenwood 1 Ton KLU-12B03S AC") == "ac"
    assert contains_forbidden_abbreviation("Kenwood 1 Ton KLU-12B03S Air Conditioner") is None


# --- The two Boss Rule title PATTERNS (owner's written spec, 2026-08-11) ----
#
# PATTERN A -- small/technical appliances, where the spec is a TECHNICAL
# DETAIL, not the product's identity (vacuum cleaner, kitchen robot, coffee
# maker, insect killer):
#     [Brand] [Model] [Series/Features] [Category] - [Technical Spec]
#     "Anex AG-2098 Deluxe 2 in 1 Vacuum Cleaner - 1500W"
#   The dash before the spec is MANDATORY here.
#
# PATTERN B -- major/capacity appliances, where capacity/size IS a core part
# of the identity (AC, refrigerator, washing machine):
#     [Brand] [Model] [Capacity] [Series/Features] [Category]
#     "Dawlance DW6570 GB 8 Kg Twin Tub Semi Automatic Washing Machine"
#   NO dash -- the capacity is integrated into the name flow.
#
# Selection is by which spec carries the identity, so capacity (when
# confirmed) wins: a product with both is a major appliance by definition.
# An earlier implementation put wattage in capacity's slot with no dash for
# every product -- that produced "Anex AG-3151 700W Deluxe Kitchen Robot",
# which is neither pattern.

def test_pattern_a_puts_the_wattage_last_after_a_dash():
    """The owner's real AG-2098 case, verbatim."""
    name = build_name("Anex", "", "AG-2098", "Vacuum Cleaner",
                      features=["Deluxe", "2 in 1"], wattage="1500W")
    assert name == "Anex AG-2098 Deluxe 2 in 1 Vacuum Cleaner - 1500W"


def test_pattern_a_reference_titles():
    assert build_name("Anex", "", "AG-3151", "Kitchen Robot",
                      features=["Deluxe"], wattage="700W") == \
        "Anex AG-3151 Deluxe Kitchen Robot - 700W"
    assert build_name("Anex", "", "AG-801", "Coffee Maker",
                      features=["Deluxe"], wattage="550W") == \
        "Anex AG-801 Deluxe Coffee Maker - 550W"
    assert build_name("Anex", "", "AG-3092", "Insect Killer",
                      features=["Deluxe"], wattage="2X10W") == \
        "Anex AG-3092 Deluxe Insect Killer - 2X10W"


def test_pattern_b_reference_titles_keep_capacity_inline_with_no_dash():
    assert build_name("Dawlance", "8 Kg", "DW6570 GB", "Washing Machine",
                      features=["Twin Tub Semi Automatic"]) == \
        "Dawlance DW6570 GB 8 Kg Twin Tub Semi Automatic Washing Machine"
    assert build_name("Haier", "14 Cu Ft", "HRF-418 IPRA", "Refrigerator",
                      features=["Purple Glass Door", "Smart Inverter"]) == \
        "Haier HRF-418 IPRA 14 Cu Ft Purple Glass Door Smart Inverter Refrigerator"


def test_a_product_with_both_capacity_and_wattage_uses_both_slots():
    """
    Owner-corrected (2026-08-11) with real microwave examples: the two slots
    are INDEPENDENT, not mutually exclusive -- capacity stays inline where
    Pattern B puts it AND the wattage still trails after the dash:
        "Anex AG-9039 Deluxe Digital Microwave With Oven - 900W"
        "Anex AG-9039 25L Deluxe Digital Microwave With Oven - 900W"
    """
    with_capacity = build_name("Anex", "25 Liters", "AG-9039", "Microwave With Oven",
                               features=["Deluxe", "Digital"], wattage="900W")
    assert with_capacity == "Anex AG-9039 25L Deluxe Digital Microwave With Oven - 900W"

    # The same product when no capacity was confirmed -- wattage slot alone.
    without_capacity = build_name("Anex", "", "AG-9039", "Microwave With Oven",
                                  features=["Deluxe", "Digital"], wattage="900W")
    assert without_capacity == "Anex AG-9039 Deluxe Digital Microwave With Oven - 900W"


def test_pattern_a_still_works_with_no_features_at_all():
    name = build_name("Anex", "", "AG-12", "Food Processor", wattage="450W")
    assert name == "Anex AG-12 Food Processor - 450W"


def test_wattage_is_never_dropped_for_length():
    """Confirmed data, not an optional feature -- must survive truncation
    the same way capacity/series already do."""
    name = build_name(
        "Anex", "", "AG-VERY-LONG-MODEL-NUMBER-EXCEEDING-EVERYTHING",
        "Kitchen Robot", wattage="700W",
        features=["Multi Function Deluxe Edition With Extra Attachments"],
    )
    assert "700W" in name


def test_wattage_is_not_duplicated_if_also_harvested_as_a_feature():
    """
    A harvested title-term phrase could independently produce "700W" as its
    own feature (e.g. a scraped title literally contains it as an n-gram) --
    without dedup this would double up: "Anex AG-3151 Deluxe 700W Kitchen
    Robot - 700W". The dedicated wattage slot is authoritative; an exact
    (case-insensitive) duplicate coming through `features` is dropped.
    """
    name = build_name("Anex", "", "AG-3151", "Kitchen Robot", wattage="700W",
                      features=["700w", "Deluxe"])
    assert name.count("700W") == 1
    assert name == "Anex AG-3151 Deluxe Kitchen Robot - 700W"


def test_no_wattage_yields_the_bare_formula_unchanged():
    """Categories without a wattage spec (ACs, fridges) are unaffected --
    omitting the argument must not alter existing behavior."""
    name = build_name("Dawlance", "1.5 Ton", "9199-B", "Air Conditioner")
    assert name == "Dawlance 9199-B 1.5 Ton Air Conditioner"


# --- Title-string sanitizer (Boss Rule Step 3: format hygiene) -------------

def test_empty_brackets_are_stripped():
    name = build_name("Anex", "", "AG-1", "Blender", features=["()"])
    assert "()" not in name
    assert "[]" not in name


def test_double_spaces_are_collapsed():
    name = build_name("Anex", "", "AG-1", "Blender", features=["Turbo  Mode"])
    assert "  " not in name


def test_trailing_hyphen_is_stripped():
    name = build_name("Anex", "", "AG-1 -", "")
    assert not name.endswith("-")
    assert not name.endswith(" -")


def test_commas_are_replaced_so_keyword_counting_is_not_disrupted():
    """
    Boss Rule #6: commas ruin Rank Math's focus-keyword counting. Replaced
    with a plain space, not the word "and" -- a title with several commas
    ("Kitchen Robot, Deluxe, 700W") would otherwise become the spammy
    "Kitchen Robot and Deluxe and 700W". A space also sidesteps a real
    category name that already legitimately contains "and" (e.g. "Grinder
    and Blender") ever being doubled up by the sanitizer.
    """
    name = build_name("Anex", "", "AG-1", "Blender", features=["Glass, Steel"])
    assert "," not in name
    assert " and " not in name
    assert "Glass" in name and "Steel" in name


def test_multiple_commas_do_not_produce_spammy_repeated_and():
    name = build_name("Anex", "", "AG-1", "Grinder and Blender",
                      features=["Glass, Steel, Copper"])
    assert name.count(" and ") == 1, "only the genuine category 'and' survives"


def test_a_category_name_that_legitimately_contains_and_is_untouched():
    """'Grinder and Blender' is a real combo-appliance category name, not
    sanitizer output -- must not be mangled."""
    name = build_name("Anex", "", "AG-1", "Grinder and Blender")
    assert "Grinder and Blender" in name


def test_series_is_not_repeated_when_it_is_also_a_harvested_feature():
    """
    Owner-reported (2026-08-12, live CSV): the exported title read "Anex
    AG-2098 Deluxe Deluxe -2 in 1 Vacuum Cleaner - 1500W". "Deluxe" arrived
    twice -- once as the extracted `series` and once as a harvested feature
    term -- and nothing deduplicated the two against each other.
    """
    name = build_name("Anex", "", "AG-2098", "Vacuum Cleaner",
                      series="Deluxe", features=["Deluxe", "2 in 1"], wattage="1500W")
    assert name.lower().count("deluxe") == 1
    assert name == "Anex AG-2098 Deluxe 2 in 1 Vacuum Cleaner - 1500W"
