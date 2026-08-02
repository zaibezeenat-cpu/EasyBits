"""
ADD vs UPDATE is decided by the sheet's optional Existing ID: when present it must
land in the CSV's `ID` column so WooCommerce updates that product in place instead
of creating a duplicate; when absent the `ID` stays empty (create new). A wrong ID
here either clones a live product or overwrites the wrong one, so it is locked.
"""
from decimal import Decimal
from uuid import uuid4

from app.builders.csv_assembler import assemble_csv_row
from app.graph.state import PipelineState
from app.models.raw_input import RawProductInput


def _state(**raw_overrides) -> PipelineState:
    base = dict(
        sku="WF-6807",
        model_number="WF-6807",
        brand_name="Westpoint",
        category_name="AC",
        product_type="Hair Straightener",
        regular_price=Decimal("6400"),
        sale_price=Decimal("6400"),
    )
    base.update(raw_overrides)
    return PipelineState(
        product_id=uuid4(),
        batch_id=uuid4(),
        raw_input=RawProductInput(**base),
        name="Westpoint WF-6807 Hair Straightener",
        short_description="<ul><li>F1</li></ul>",
        description="Full Desc",
        specs_table_html="<table></table>",
        resolved_warranty_phrase="2 Years Warranty",
    )


def _assemble(state):
    return assemble_csv_row(
        state, "Electronics > AC", "Westpoint",
        canonical_category_path="Electronics > AC",
    )


def test_existing_id_fills_the_csv_id_column_for_update():
    row = _assemble(_state(existing_id="10874"))
    assert row["ID"] == "10874"


def test_no_existing_id_leaves_id_empty_for_create():
    row = _assemble(_state())
    assert row["ID"] == ""


def test_blank_existing_id_is_treated_as_create():
    # An empty string from a blank sheet cell must not be written as an "ID" that
    # WooCommerce would try (and fail) to match.
    row = _assemble(_state(existing_id=""))
    assert row["ID"] == ""
