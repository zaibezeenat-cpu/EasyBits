"""
Tests for warranty cross-checking.

Warranty is the highest-stakes field in the system: it is hand-typed into the
input sheet, repeated in four places on the live product, and is a claim the
business is then obliged to honour. Publishing "10 years" when the real cover is
1 year is a commercial liability, not a formatting bug.
"""

import pytest

from app.builders.warranty_verifier import (
    build_source_text,
    extract_durations,
    verify_warranty,
    warranty_conflict_detail,
)


async def _no_setting(_key):
    """Stand-in for settings_repo.get_setting so unit tests never touch Supabase."""
    return


# --- Duration extraction ----------------------------------------------------


def test_extracts_multiple_durations_from_a_real_warranty_phrase():
    durations = extract_durations(
        "10 Years Compressor Warranty; 5 Years All Parts Warranty"
    )
    assert durations == ["10 year", "5 year"]


def test_abbreviated_forms_are_understood():
    assert extract_durations("10-yr compressor, 2 yrs parts") == ["10 year", "2 year"]


def test_months_convert_to_years_when_they_divide_evenly():
    """ "24 months" and "2 years" are the same cover and must not look like a conflict."""
    assert extract_durations("24 months warranty") == ["2 year"]
    assert extract_durations("18 months warranty") == ["18 month"]


def test_no_duration_returns_empty():
    assert extract_durations("Official Warranty") == []
    assert extract_durations("") == []


# --- Verification -----------------------------------------------------------


def test_matching_warranty_is_confirmed():
    check = verify_warranty(
        "10 Years Compressor Warranty; 5 Years All Parts Warranty",
        "This unit ships with a 10 year compressor warranty and 5 years on all parts.",
    )
    assert check.checked and check.agrees
    assert warranty_conflict_detail(check) is None


def test_direct_same_component_contradiction_is_flagged():
    """
    A REAL conflict: the sources give a different number for the SAME component.
    10-year compressor on the sheet vs 5-year compressor in a source.
    """
    check = verify_warranty(
        "10 Years Compressor Warranty",
        "This model includes only a 5 year compressor warranty.",
    )
    assert check.checked
    assert not check.agrees
    detail = warranty_conflict_detail(check)
    assert detail is not None
    assert "10 year" in detail and "5 year" in detail


def test_generic_source_warranty_is_not_a_contradiction():
    """
    Owner policy (2026-07-22): the operator's warranty is authoritative. A
    source's generic "1 year manufacturer warranty" names no specific component,
    so it does NOT contradict a 10-year compressor claim -- a manufacturer can
    offer 1-year general cover alongside a 10-year compressor. Must be accepted.
    """
    check = verify_warranty(
        "10 Years Compressor Warranty; 5 Years All Parts Warranty",
        "Includes a 1 year manufacturer warranty only.",
    )
    assert check.checked and check.agrees
    assert warranty_conflict_detail(check) is None


@pytest.mark.asyncio
async def test_retailer_warranty_difference_does_not_escalate(monkeypatch):
    """
    Owner policy: warranty is cross-checked against OFFICIAL brand sources only.
    A retailer (trusted_secondary) stating a different number must NOT escalate,
    because the sheet warranty comes from the brand's official declaration and
    outranks any retailer. This is the exact Haier pilot situation: surmawala
    stated "3 year parts", the sheet (correct) said "1 year other parts".
    """
    from decimal import Decimal
    from uuid import uuid4

    from app.graph import nodes
    from app.graph.state import PipelineState
    from app.models.raw_input import RawProductInput

    async def fake_scrape(_brand, _model, **_kw):
        return {
            "scraped_data": [
                {
                    "url": "https://surmawala.pk/products/x",
                    "source_type": "trusted_secondary",
                    "content": "Haier HRF-246 IPGA. 3 year parts warranty. Smart Inverter.",
                }
            ]
        }

    monkeypatch.setattr(nodes, "scrape_product", fake_scrape)
    # extractor_node reads provided_source_mode from app_settings before it
    # scrapes. Unpatched that is a REAL Supabase round-trip, so this test only
    # passed on a machine with a reachable database and failed in CI (which sets
    # SUPABASE_URL=http://localhost). None selects the "augment" default.
    monkeypatch.setattr(nodes.settings_repo, "get_setting", _no_setting)

    state = PipelineState(
        product_id=uuid4(),
        batch_id=uuid4(),
        raw_input=RawProductInput(
            sku="HRF-246-IPGA",
            model_number="HRF-246 IPGA",
            brand_name="HAIER",
            category_name="Refrigerator",
            product_type="Refrigerator",
            regular_price=Decimal(90000),
            sale_price=Decimal(74999),
            warranty_override="Compressor: 10 Year * Other part: 1 Year",
        ),
    )

    result = await nodes.extractor_node(state)
    # Whatever else happens downstream, it must NOT be a warranty conflict.
    assert (
        result.get("failure") is None
        or result["failure"].category != "warranty_conflict"
    )


def test_electronics_part_tier_does_not_collide_with_other_parts_tier():
    """
    The exact false positive the Haier pilot caught. Haier's electronics tier is
    worded "Electronics part (...): 3 Year" -- it contains the word "part". A
    naive "parts" bucket swallowed that 3-year value and then reported a
    contradiction against the genuine "Other part: 1 Year" tier. With
    most-specific-bucket-wins, the electronics tier stays in electronics and
    there is no contradiction.
    """
    sheet = (
        "Compressor Including Gas: 10 Year Warranty * "
        "Electronics part (VFD, PCB, Thermostat, Digital display, Fan & LED Lights): 3 Year Warranty * "
        "Other part including Gas: 1 Year Warranty"
    )
    # A source that also spells the electronics tier with the word "part".
    source = "10 year compressor warranty. Electronics part covered 3 year. Turbo fan."
    check = verify_warranty(sheet, source)
    assert check.agrees, check.detail
    assert warranty_conflict_detail(check) is None


def test_real_same_component_contradiction_survives_the_bucket_fix():
    """The fix must not silence a genuine compressor-vs-compressor disagreement."""
    check = verify_warranty(
        "Compressor: 10 Year * Other part: 1 Year",
        "Compressor warranty is only 5 year on this unit.",
    )
    assert not check.agrees
    assert "compressor" in (warranty_conflict_detail(check) or "")


def test_haier_three_tier_warranty_accepted_when_sources_list_fewer_tiers():
    """
    The exact Haier pilot case. The sheet's three tiers are correct (confirmed
    against haier.com/pk), retailers listed only the headline cover, and the old
    rule wrongly escalated it. The operator warranty must now be accepted.
    """
    check = verify_warranty(
        "Compressor Including Gas: 10 Year Warranty; "
        "Electronics part (VFD, PCB, Thermostat): 3 Year Warranty; "
        "Other part including Gas: 1 Year Warranty",
        "Haier HRF-246 IPGA Smart Inverter. 10 year compressor warranty, 3 year on electronics.",
    )
    assert check.checked and check.agrees
    assert warranty_conflict_detail(check) is None


def test_sources_silent_on_warranty_is_not_a_conflict():
    """
    Most retailer pages never mention warranty. That means "nothing to compare",
    NOT "verified" and NOT "conflict" -- it must not block the pipeline.
    """
    check = verify_warranty(
        "1 Year Official Warranty", "Kenwood 1.0 Ton Inverter AC. Rs 150,000."
    )
    assert check.checked is False
    assert warranty_conflict_detail(check) is None


def test_source_listing_extra_cover_is_not_a_conflict():
    """
    Sources often list additional cover the operator chose not to advertise.
    Only the operator's claims must be supported, not the other way round.
    """
    check = verify_warranty(
        "2 years parts warranty",
        "10 years compressor warranty and 2 years parts warranty included.",
    )
    assert check.checked and check.agrees


def test_months_vs_years_do_not_produce_a_false_conflict():
    check = verify_warranty("2 Year Warranty", "Backed by a 24 months warranty.")
    assert check.agrees, "24 months and 2 years are the same cover"


def test_unparseable_input_warranty_is_not_verified():
    check = verify_warranty("Official Warranty", "10 year compressor warranty")
    assert check.checked is False
    assert warranty_conflict_detail(check) is None


def test_build_source_text_concatenates_all_sources():
    text = build_source_text(
        [
            {"content": "10 year compressor"},
            {"content": "5 years parts"},
        ]
    )
    assert "10 year compressor" in text and "5 years parts" in text
    assert build_source_text([]) == ""


# --- Pipeline integration ---------------------------------------------------


@pytest.mark.asyncio
async def test_warranty_mismatch_routes_product_to_manual_review(monkeypatch):
    """
    End-to-end guard: a scraped warranty that contradicts the sheet must send the
    product to Manual Review with a warranty_conflict reason, never be approved.
    """
    from decimal import Decimal
    from uuid import uuid4

    from app.graph import nodes
    from app.graph.state import PipelineState
    from app.models.raw_input import RawProductInput

    async def fake_scrape(_brand, _model, **_kw):
        return {
            "scraped_data": [
                {
                    "url": "https://kenwood.com.pk/products/x",
                    # Warranty is only cross-checked against OFFICIAL sources, so the
                    # contradiction must come from one to escalate.
                    "source_type": "official",
                    # A DIRECT contradiction on the same component: sheet claims a
                    # 10-year compressor, this source states 5-year.
                    "content": "Kenwood KLU-12B03S. Includes only a 5 year compressor warranty.",
                }
            ]
        }

    monkeypatch.setattr(nodes, "scrape_product", fake_scrape)
    # See the note in test_retailer_warranty_difference_does_not_escalate: this
    # settings read is a live DB call unless it is patched out.
    monkeypatch.setattr(nodes.settings_repo, "get_setting", _no_setting)

    state = PipelineState(
        product_id=uuid4(),
        batch_id=uuid4(),
        raw_input=RawProductInput(
            sku="KLU-12B03S",
            model_number="KLU-12B03S",
            brand_name="Kenwood",
            category_name="Air conditioner",
            product_type="Air conditioner",
            regular_price=Decimal(150000),
            sale_price=Decimal(139999),
            warranty_override="10 Years Compressor Warranty; 5 Years All Parts Warranty",
        ),
    )

    result = await nodes.extractor_node(state)

    assert result["manual_review_required"] is True
    assert result["failure"].category == "warranty_conflict"
    assert "10 year" in result["failure"].detail
    assert "5 year" in result["failure"].detail
