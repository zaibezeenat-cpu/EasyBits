"""
Deducing a spec the sources describe but never name.

THE PROBLEM (operator, 2026-08-07)
----------------------------------
A manual chopper has no wattage. A vacuum's listing describes "flexible hose,
extension tube, big dust bag" without ever printing the word "canister". Both
products were blocked in Manual Review over a field the sources could not state
in the form the schema wanted -- and with no usable frontend, a blocked product
is lost work, not deferred work.

An earlier attempt filtered the missing-field list against
`CORE_FIELDS = {"title", "brand", "regular_price", "category"}`. Three of those
four are CSV columns, not spec-schema keys, so the filter emptied the list: with
an official source present a product could ship missing its model_number and
every measurement. These tests pin the mechanism that replaced it.

THE RULE
--------
The category schema decides, per field:
    required=True,  inferable=False -> no source states it: escalate
    required=True,  inferable=True  -> may be DEDUCED, cited as "inferred"
    required=False                  -> skipped silently

An inference never counts as confirmed, and code -- not the prompt -- enforces
which fields may carry one.
"""
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.models.extraction import ExtractionResult, SourceCitation
from app.models.taxonomy import CategorySpecSchema, SpecField

NOW = datetime.now(UTC)


def _schema(*fields: SpecField) -> CategorySpecSchema:
    from uuid import uuid4
    return CategorySpecSchema(
        id=uuid4(), category_id=uuid4(), fields=list(fields),
        created_at=NOW, updated_at=NOW,
    )


def _cite(field: str, value: str, confidence: str = "confirmed", **kw) -> SourceCitation:
    return SourceCitation(
        field_name=field, value=value,
        source_url=kw.pop("source_url", "https://brand.pk/p"),
        source_type=kw.pop("source_type", "official"),
        confidence=confidence, fetched_at=NOW, **kw,
    )


def _result(*citations: SourceCitation) -> ExtractionResult:
    return ExtractionResult(product_id="p1", category_key="vacuum", citations=list(citations))


VACUUM_TYPE = SpecField(key="vacuum_type", label="Vacuum Type", required=True, inferable=True)
WATTAGE = SpecField(key="wattage", label="Wattage", required=True)  # inferable defaults False


# --- the citation contract --------------------------------------------------

def test_an_inference_must_carry_its_evidence():
    """Without the quote nobody can tell a deduction from a guess."""
    with pytest.raises(ValidationError, match="exact_quote"):
        _cite("vacuum_type", "Canister", confidence="inferred")


def test_an_inference_with_evidence_is_accepted():
    c = _cite("vacuum_type", "Canister", confidence="inferred",
              exact_quote="flexible hose, extension tube, big dust bag")
    assert c.confidence == "inferred"


def test_inferring_unknown_is_rejected_as_meaningless():
    with pytest.raises(ValidationError):
        _cite("vacuum_type", "UNKNOWN", confidence="inferred", exact_quote="something")


# --- inference never becomes a verified fact --------------------------------

def test_a_deduced_value_is_never_confirmed():
    """
    THE LOAD-BEARING PROPERTY. Every guard downstream keys off is_confirmed, so
    if a deduction could satisfy it the whole no-hallucination contract leaks.
    """
    r = _result(_cite("vacuum_type", "Canister", confidence="inferred",
                      exact_quote="flexible hose and dust bag"))
    resolution = r.resolve("vacuum_type")

    assert resolution.status == "inferred"
    assert resolution.is_confirmed is False
    assert resolution.is_inferred is True
    assert resolution.is_usable is True          # publishable, but explicitly so
    assert r.confirmed_value("vacuum_type") is None
    assert r.inferred_value("vacuum_type") == "Canister"


def test_a_stated_value_always_beats_a_deduction():
    """A real citation must win outright, not compete with an inference."""
    r = _result(
        _cite("vacuum_type", "Drum"),
        _cite("vacuum_type", "Canister", confidence="inferred", exact_quote="hose"),
    )
    assert r.confirmed_value("vacuum_type") == "Drum"
    assert r.resolve("vacuum_type").is_confirmed


# --- code, not the prompt, decides what may be inferred ---------------------

def test_an_inference_for_a_non_inferable_field_is_discarded():
    """
    The prompt is told which fields are inferable. A model that ignores that and
    deduces a wattage anyway has to be stopped here -- guessing a number is the
    failure this pipeline exists to prevent.
    """
    schema = _schema(VACUUM_TYPE, WATTAGE)
    r = _result(_cite("wattage", "1200 W", confidence="inferred",
                      exact_quote="powerful motor"))

    dropped = r.drop_disallowed_inferences(schema)

    assert dropped == ["wattage"]
    assert r.inferred_value("wattage") is None
    assert "wattage" in r.missing_required_fields(schema)


def test_an_inference_for_an_unmodelled_field_is_discarded():
    schema = _schema(VACUUM_TYPE)
    r = _result(_cite("colour", "Red", confidence="inferred", exact_quote="red body"))
    assert r.drop_disallowed_inferences(schema) == ["colour"]


def test_allowed_inferences_survive_the_filter():
    schema = _schema(VACUUM_TYPE, WATTAGE)
    r = _result(_cite("vacuum_type", "Canister", confidence="inferred",
                      exact_quote="flexible hose, extension tube, big dust bag"))

    assert r.drop_disallowed_inferences(schema) == []
    assert r.inferred_value("vacuum_type") == "Canister"


# --- the escalation decision ------------------------------------------------

def test_a_deduced_inferable_field_is_not_reported_missing():
    """The point of the flag: the product ships instead of being blocked."""
    schema = _schema(VACUUM_TYPE)
    r = _result(_cite("vacuum_type", "Canister", confidence="inferred",
                      exact_quote="flexible hose, extension tube, big dust bag"))

    assert r.missing_required_fields(schema) == []


def test_a_non_inferable_field_still_blocks_when_absent():
    """Measurements keep the old behaviour -- no source, no ship."""
    schema = _schema(WATTAGE)
    assert _result().missing_required_fields(schema) == ["wattage"]


def test_an_optional_field_never_blocks():
    """The manual-chopper fix: wattage marked not-required for that category."""
    schema = _schema(SpecField(key="wattage", label="Wattage", required=False))
    assert _result().missing_required_fields(schema) == []


def test_inferable_does_not_excuse_a_field_nothing_could_deduce():
    """`inferable` permits a deduction; it does not invent one."""
    schema = _schema(VACUUM_TYPE)
    assert _result().missing_required_fields(schema) == ["vacuum_type"]


# --- reporting --------------------------------------------------------------

def test_deduced_fields_and_their_evidence_are_retrievable():
    """Feeds the CLI report -- the operator's only review surface."""
    schema = _schema(VACUUM_TYPE)
    quote = "flexible hose, extension tube, big dust bag"
    r = _result(_cite("vacuum_type", "Canister", confidence="inferred", exact_quote=quote))

    assert r.inferred_fields(schema) == {"vacuum_type": "Canister"}
    assert r.inference_evidence("vacuum_type") == quote


def test_fields_default_to_not_inferable():
    """Safety by default: a schema written without thinking about this is strict."""
    assert SpecField(key="x", label="X").inferable is False


# ---------------------------------------------------------------------------
# THE MECHANISM MUST BE CATEGORY-AGNOSTIC.
#
# Everything above is proved with a vacuum cleaner, which proves it works for a
# vacuum cleaner. The mechanism reads `inferable` off whatever SpecField it is
# handed and knows nothing about product types -- but "should be general" is a
# claim, and a claim about behaviour belongs in a test.
#
# These run the same three rules across every category the catalogue actually
# sells, with that category's real fields and real source wording.
# ---------------------------------------------------------------------------

# (category, field, deduced value, the words a real listing would carry)
CATEGORICAL_CASES = [
    ("Vacuum Cleaner", "vacuum_type", "Canister",
     "flexible hose, extension tube, big dust bag"),
    ("Washing Machine", "washing_machine_type", "Twin Tub",
     "separate wash and spin tubs"),
    ("Air Conditioner", "compressor_type", "Inverter",
     "DC inverter compressor saves up to 60% electricity"),
    ("Refrigerator", "door_type", "Double Door",
     "separate freezer compartment with its own door"),
    ("Microwave Oven", "control_type", "Digital",
     "digital touch panel with 10 preset menus"),
    ("Manual Chopper", "operation_type", "Manual",
     "pull-cord operated, no electricity required"),
    ("Blender", "jar_material", "Glass",
     "heat-resistant glass jar, dishwasher safe"),
    ("Water Dispenser", "cooling_type", "Compressor",
     "compressor cooling with refrigerant"),
]

# Measurements, one per category. None of these may EVER be deduced -- there is
# no evidence a number follows from, only a guess.
MEASUREMENT_CASES = [
    ("Vacuum Cleaner", "wattage", "1800 W", "powerful suction motor"),
    ("Washing Machine", "capacity_kg", "8 kg", "large family-size drum"),
    ("Air Conditioner", "capacity_ton", "1.5 Ton", "cools a medium room quickly"),
    ("Refrigerator", "capacity_litres", "340 L", "spacious interior"),
    ("Microwave Oven", "capacity_litres", "25 L", "roomy cavity"),
    ("Blender", "wattage", "600 W", "strong motor for hard ingredients"),
]


@pytest.mark.parametrize("category,field,value,evidence", CATEGORICAL_CASES)
def test_any_category_may_deduce_a_field_it_marks_inferable(category, field, value, evidence):
    schema = _schema(SpecField(key=field, label=field, required=True, inferable=True))
    r = _result(_cite(field, value, confidence="inferred", exact_quote=evidence))

    assert r.drop_disallowed_inferences(schema) == [], f"{category}: allowed inference was dropped"
    assert r.inferred_value(field) == value, f"{category}: deduction lost"
    assert r.missing_required_fields(schema) == [], f"{category}: still blocked despite a deduction"
    assert not r.resolve(field).is_confirmed, f"{category}: deduction became a verified fact"


@pytest.mark.parametrize("category,field,value,evidence", MEASUREMENT_CASES)
def test_no_category_may_deduce_a_measurement(category, field, value, evidence):
    """
    The rule that must hold everywhere. A wrong number on a live listing is the
    failure this pipeline exists to prevent, and it does not become acceptable
    because the category changed.
    """
    schema = _schema(SpecField(key=field, label=field, required=True))  # inferable defaults False
    r = _result(_cite(field, value, confidence="inferred", exact_quote=evidence))

    assert r.drop_disallowed_inferences(schema) == [field], f"{category}: a measurement was deduced"
    assert r.inferred_value(field) is None, f"{category}: deduced measurement survived"
    assert field in r.missing_required_fields(schema), f"{category}: absent measurement did not block"


@pytest.mark.parametrize("category,field,_v,_e", CATEGORICAL_CASES + MEASUREMENT_CASES)
def test_any_category_can_mark_a_field_optional(category, field, _v, _e):
    """The manual-chopper fix generalised: required=False never blocks, anywhere."""
    schema = _schema(SpecField(key=field, label=field, required=False))
    assert _result().missing_required_fields(schema) == [], f"{category}: optional field blocked"


@pytest.mark.parametrize("category,field,value,evidence", CATEGORICAL_CASES)
def test_a_stated_value_beats_a_deduction_in_every_category(category, field, value, evidence):
    """A real citation must win outright wherever it appears."""
    schema = _schema(SpecField(key=field, label=field, required=True, inferable=True))
    r = _result(
        _cite(field, "StatedValue"),
        _cite(field, value, confidence="inferred", exact_quote=evidence),
    )
    r.drop_disallowed_inferences(schema)
    assert r.confirmed_value(field) == "StatedValue", f"{category}: deduction outranked a source"


def test_a_mixed_schema_applies_each_rule_per_field():
    """
    The realistic shape: one category, several fields, different rules. A vacuum
    may deduce its type, must never deduce its wattage, and does not care about
    an optional colour -- all at once.
    """
    schema = _schema(
        SpecField(key="vacuum_type", label="Type", required=True, inferable=True),
        SpecField(key="wattage", label="Wattage", required=True),
        SpecField(key="colour", label="Colour", required=False),
    )
    r = _result(
        _cite("vacuum_type", "Canister", confidence="inferred", exact_quote="hose and dust bag"),
        _cite("wattage", "1800 W", confidence="inferred", exact_quote="powerful motor"),
    )

    assert r.drop_disallowed_inferences(schema) == ["wattage"]
    assert r.inferred_value("vacuum_type") == "Canister"   # deduced, allowed
    assert r.missing_required_fields(schema) == ["wattage"]  # blocked, correctly
    # colour is optional and absent -- it must not appear anywhere
    assert "colour" not in r.missing_required_fields(schema)
