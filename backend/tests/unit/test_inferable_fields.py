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
