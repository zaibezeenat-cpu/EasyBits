"""
Regression lock for the corroboration bug at the ExtractionResult level.

Before the fix, ExtractionResult.confirmed_value() returned a value only when
exactly one confirmed citation existed. Two sources agreeing (len == 2) returned
None, so the field looked missing and the product escalated. This proves
agreement now confirms.
"""
from datetime import datetime

from app.models.extraction import ExtractionResult, SourceCitation


def _cite(field, value, url, source_type="trusted_secondary"):
    return SourceCitation(
        field_name=field, value=value, source_url=url,
        source_type=source_type, confidence="confirmed", fetched_at=datetime.now(),
    )


def _result(citations):
    return ExtractionResult(product_id="p", category_key="refrigerator", citations=citations)


def test_two_agreeing_sources_now_confirm():
    er = _result([
        _cite("capacity", "9 Cu Ft", "https://japanelectronics.pk/x"),
        _cite("capacity", "9 cubic feet", "https://surmawala.pk/y"),
    ])
    assert er.confirmed_value("capacity") is not None
    assert er.has_conflict("capacity") is False
    assert er.resolve("capacity").status == "corroborated"


def test_wording_difference_is_not_a_conflict():
    """'9 Cu Ft' vs '9 cubic feet' must normalise to agreement, not a conflict."""
    er = _result([
        _cite("capacity", "9 Cu Ft", "https://a.pk/x"),
        _cite("capacity", "9 CUBIC FEET", "https://b.pk/y"),
    ])
    assert er.has_conflict("capacity") is False


def test_genuine_disagreement_still_conflicts_and_blocks_the_value():
    er = _result([
        _cite("capacity", "9 Cu Ft", "https://a.pk/x"),
        _cite("capacity", "12 Cu Ft", "https://b.pk/y"),
    ])
    assert er.has_conflict("capacity") is True
    assert er.confirmed_value("capacity") is None


def test_single_official_source_still_confirms():
    er = _result([_cite("capacity", "9 Cu Ft", "https://haier.com/pk/x", "official")])
    assert er.confirmed_value("capacity") == "9 Cu Ft"


def test_single_source_value_is_now_confirmed():
    """
    2026-08-09 relaxation: a single unverified retailer IS now published (see
    ExtractionResult.confirmed_value's docstring) -- two-source corroboration
    was blocking most products since few brands have a registered official
    domain and only 1-2 trusted retailers are usually configured.
    `single_source_value` still reports the weaker confidence tier for the QA
    panel even though the value is no longer withheld.
    """
    er = _result([_cite("capacity", "346", "https://japanelectronics.pk/x")])
    assert er.confirmed_value("capacity") == "346"
    assert er.single_source_value("capacity") == "346"


def test_single_source_required_field_is_no_longer_flagged_for_review():
    from uuid import uuid4

    from app.models.taxonomy import CategorySpecSchema, SpecField

    now = datetime.now()
    schema = CategorySpecSchema(
        id=uuid4(), category_id=uuid4(),
        fields=[SpecField(key="capacity", label="Capacity", required=True)],
        created_at=now, updated_at=now,
    )
    er = _result([_cite("capacity", "346", "https://japanelectronics.pk/x")])
    issues = er.uncorroborated_required_fields(schema)
    assert "capacity" not in issues


def test_two_sources_agreeing_ARE_confirmed_and_publishable():
    """The counterpart: real corroboration passes and is used."""
    er = _result([
        _cite("capacity", "9 Cu Ft", "https://japanelectronics.pk/x"),
        _cite("capacity", "9 cubic feet", "https://surmawala.pk/y"),
    ])
    assert er.confirmed_value("capacity") is not None


def test_missing_required_fields_uses_corroboration():
    """A corroborated field must NOT be reported as missing."""
    from uuid import uuid4

    from app.models.taxonomy import CategorySpecSchema, SpecField

    now = datetime.now()
    schema = CategorySpecSchema(
        id=uuid4(), category_id=uuid4(),
        fields=[SpecField(key="capacity", label="Capacity", required=True)],
        created_at=now, updated_at=now,
    )
    er = _result([
        _cite("capacity", "9 Cu Ft", "https://a.pk/x"),
        _cite("capacity", "9 cubic feet", "https://b.pk/y"),
    ])
    assert "capacity" not in er.missing_required_fields(schema)
