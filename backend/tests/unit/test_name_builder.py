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
