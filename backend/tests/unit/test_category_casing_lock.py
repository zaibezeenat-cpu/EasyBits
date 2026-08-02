"""
Proves the Category Casing Lock.

WHY THIS IS A JOB-RISK PATH
---------------------------
WooCommerce matches taxonomy terms by EXACT string. "Air conditioner" and
"air conditioner" are not the same term -- importing the second one does not
file the product under the existing category, it CREATES A SECOND CATEGORY in
the live store. The same applies to brands. Cleaning that up by hand across a
live catalogue is the failure the owner cannot afford.

The brand side was already locked twice (intake + CSV assembly). The category
side was locked only indirectly, by the breadcrumb assertion -- which these
tests show was not sufficient.
"""
from decimal import Decimal
from uuid import uuid4

import pytest

from app.builders.csv_assembler import (
    CategoryBreadcrumbError,
    CategoryCasingMismatchError,
    assemble_csv_row,
)
from app.graph.state import PipelineState
from app.models.raw_input import RawProductInput


@pytest.fixture
def minimal_state() -> PipelineState:
    return PipelineState(
        product_id=uuid4(),
        batch_id=uuid4(),
        raw_input=RawProductInput(
            sku="TEST-SKU-1",
            model_number="MODEL-123",
            brand_name="Kenwood",
            category_name="Air conditioner",
            product_type="Air Conditioner",
            regular_price=Decimal("100"),
            sale_price=Decimal("90"),
        ),
        name="Kenwood MODEL-123 Air Conditioner",
        tags="Kenwood, Air conditioner, HW",
        short_description="<ul><li>F1</li></ul>",
        description="Full Desc",
        specs_table_html="<table></table>",
        resolved_warranty_phrase="1-Year",
    )


def test_wrong_cased_category_with_a_breadcrumb_is_rejected(minimal_state):
    """
    THE HOLE THIS CLOSES.

    A bare wrong-cased name ("air conditioner") was already stopped by the
    breadcrumb assertion, because it contains no " > ". But an operator who
    types the breadcrumb themselves with the wrong casing produced a value that
    satisfied the breadcrumb check and went straight into the CSV -- creating
    "home appliance > air conditioner" as a NEW category in the live store.
    """
    with pytest.raises(CategoryCasingMismatchError):
        assemble_csv_row(
            minimal_state,
            "home appliance > air conditioner",
            "Kenwood",
            canonical_brand_name="Kenwood",
            canonical_category_path="Home Appliance > Air conditioner",
        )


def test_exactly_matching_category_path_is_accepted(minimal_state):
    row = assemble_csv_row(
        minimal_state,
        "Home Appliance > Air conditioner",
        "Kenwood",
        canonical_brand_name="Kenwood",
        canonical_category_path="Home Appliance > Air conditioner",
    )
    assert row["Categories"] == "Home Appliance > Air conditioner"


def test_top_level_category_without_a_parent_is_accepted(minimal_state):
    """
    A legitimate TOP-LEVEL category (e.g. "Beauty", where hair straighteners live)
    has no parent, so its breadcrumb is just its own name -- no " > ". The old
    blanket breadcrumb check wrongly rejected these; the exact-canonical match now
    accepts a verified top-level category while still rejecting unverified ones.
    """
    row = assemble_csv_row(
        minimal_state,
        "Beauty",
        "Kenwood",
        canonical_brand_name="Kenwood",
        canonical_category_path="Beauty",
    )
    assert row["Categories"] == "Beauty"


def test_a_single_changed_letter_is_still_a_mismatch(minimal_state):
    """One letter is enough to create a duplicate term in WooCommerce."""
    with pytest.raises(CategoryCasingMismatchError):
        assemble_csv_row(
            minimal_state,
            "Home Appliance > Air Conditioner",  # capital C
            "Kenwood",
            canonical_brand_name="Kenwood",
            canonical_category_path="Home Appliance > Air conditioner",
        )


def test_unresolved_category_cannot_reach_the_csv(minimal_state):
    """
    When the category could not be resolved against live taxonomy at all, there
    is no canonical value to compare against. The row must fail rather than
    export an unverified term.
    """
    with pytest.raises((CategoryCasingMismatchError, CategoryBreadcrumbError)):
        assemble_csv_row(
            minimal_state,
            "Some Parent > Some Unknown Category",
            "Kenwood",
            canonical_brand_name="Kenwood",
            canonical_category_path=None,
        )


def test_bare_category_without_breadcrumb_still_rejected(minimal_state):
    with pytest.raises((CategoryBreadcrumbError, CategoryCasingMismatchError)):
        assemble_csv_row(
            minimal_state,
            "Air conditioner",
            "Kenwood",
            canonical_brand_name="Kenwood",
            canonical_category_path="Home Appliance > Air conditioner",
        )
