"""
LSI keywords must describe THIS product, not its category.

Reported from production (2026-08-06): two consecutive runs of the same hair
straightener produced "beauty tools for hair", "hair straightening at home" and
"lightweight hair straightener". None of those say anything about WF-6807, and
the last one asserts something no source confirmed -- the same fabrication the
rest of the pipeline refuses for a wattage or a capacity.

The fixtures below are the REAL keywords from those two runs, and the real
confirmed facts from the same products.
"""
import pytest

from app.builders.lsi_keywords import is_product_specific, repair_lsi_keywords

# Exactly what the extractor confirmed for WF-6807 on the real run.
FACTS = {
    "brand": "Westpoint",
    "model_number": "WF-6807",
    "appliance_type": "Hair Straightener",
    "wattage": "35 Watts",
    "voltage": "220 - 240V - 50Hz",
    "plate_material": "Ceramic Coating Plate",
    "temperature_range": "215 ± 15°C",
    "features": "On/Off Switch with Power Indicator Light, PTC Heater, Locked Handle",
    "weight": "0.5 kg",
}
BRAND, MODEL, PTYPE = "WestPoint Pakistan", "WF-6807", "Hair Straightener"


def _specific(keyword: str) -> bool:
    return is_product_specific(keyword, BRAND, MODEL, PTYPE, FACTS)


@pytest.mark.parametrize("keyword", [
    "ceramic hair straightener",        # "ceramic" <- confirmed Ceramic Coating Plate
    "WF-6807 price in Pakistan",        # names the model
    "WestPoint hair straightener",      # names the brand
    "35 Watts hair straightener",       # confirmed wattage
    "PTC Heater straightener",          # confirmed feature
])
def test_keywords_anchored_to_a_confirmed_fact_are_kept(keyword):
    assert _specific(keyword)


@pytest.mark.parametrize("keyword", [
    "beauty tools for hair",            # real run 2 output
    "hair straightening at home",       # real run 2 output
    "hair straightener for frizzy hair",  # real run 1 output
    "lightweight hair straightener",    # real run 1 -- unverified CLAIM
    "best hair straightener 2026",
    "",
])
def test_category_filler_and_unverified_claims_are_rejected(keyword):
    assert not _specific(keyword)


def test_the_product_type_alone_never_anchors_a_keyword():
    """
    THE SUBTLETY THAT MADE THE FIRST ATTEMPT USELESS. The product type is itself
    a confirmed fact, so counting it as an anchor passes every category phrase --
    "beauty tools for hair" contains "hair" -- and the filter approves exactly
    what it exists to remove.
    """
    assert not _specific("hair straightener")
    assert not _specific("buy hair straightener")


def test_unconfirmed_facts_do_not_anchor():
    """A field the extractor could not confirm must not legitimise a keyword --
    otherwise the guard launders an unverified value into the CSV."""
    facts = {**FACTS, "plate_material": None, "wattage": "UNKNOWN"}
    assert not is_product_specific("ceramic hair straightener", BRAND, MODEL, PTYPE, facts)
    assert not is_product_specific("35 Watts hair straightener", BRAND, MODEL, PTYPE, facts)


# --- repair_lsi_keywords ----------------------------------------------------

def _repair(proposed):
    return repair_lsi_keywords(
        proposed, brand=BRAND, model=MODEL, product_type=PTYPE, facts=FACTS
    )


def test_real_run_1_keywords_are_cleaned_up():
    kept, rejected = _repair([
        "ceramic hair straightener",
        "hair straightener for frizzy hair",
        "lightweight hair straightener",
    ])
    assert "ceramic hair straightener" in kept          # the one good angle survives
    assert "hair straightener for frizzy hair" in rejected
    assert "lightweight hair straightener" in rejected
    assert all(_specific(k) for k in kept), f"a rejected-grade keyword survived: {kept}"


def test_real_run_2_keywords_are_cleaned_up():
    kept, rejected = _repair([
        "hair straightening at home",
        "ceramic hair straighteners",
        "beauty tools for hair",
    ])
    assert "ceramic hair straighteners" in kept
    assert set(rejected) == {"hair straightening at home", "beauty tools for hair"}
    assert all(_specific(k) for k in kept)


def test_slots_are_refilled_when_everything_is_rejected():
    """The schema demands at least 2 LSI keywords, so dropping bad ones is only
    half the job -- replacements must come from the confirmed facts."""
    kept, rejected = _repair(["beauty tools", "best straightener", "top rated"])
    assert len(rejected) == 3
    assert len(kept) >= 2
    assert all(_specific(k) for k in kept)


def test_output_respects_the_schema_bounds():
    kept, _ = _repair(["a", "b", "c", "d", "e", "f"])
    assert 2 <= len(kept) <= 3


def test_duplicates_are_collapsed():
    kept, _ = _repair(["ceramic hair straightener", "Ceramic Hair Straightener"])
    assert len(kept) == len({k.lower() for k in kept})


def test_originals_are_kept_when_there_is_nothing_verifiable_to_build_from():
    """
    With no brand, model or confirmed fact there is nothing to anchor to and
    nothing to synthesise. Returning the Writer's originals beats emitting an
    invalid WriterOutput and failing the whole product over keywords.
    """
    proposed = ["some phrase", "another phrase"]
    kept, _ = repair_lsi_keywords(
        proposed, brand="", model="", product_type="", facts={}
    )
    assert kept == proposed
