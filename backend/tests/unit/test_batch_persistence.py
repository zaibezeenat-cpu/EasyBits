"""
Tests for mapping a finished pipeline run onto the products table.

This mapping did not exist at all: `run_batch` computed a complete, correct
result and then discarded it, persisting nothing. The QA Panel, CSV export and
dashboard all had nothing to show no matter how well the pipeline ran.
"""
from decimal import Decimal
from uuid import uuid4

from app.graph.batch_processor import _final_state_to_product_update
from app.graph.state import PipelineState
from app.models.dimensions import DimensionsResult
from app.models.failure import FailureInfo
from app.models.raw_input import RawProductInput


def _state(**overrides) -> PipelineState:
    base = dict(
        product_id=uuid4(), batch_id=uuid4(),
        raw_input=RawProductInput(
            sku="KLU-12B03S", model_number="KLU-12B03S", brand_name="Kenwood",
            category_name="Air conditioner", product_type="Air conditioner",
            regular_price=Decimal("150000"), sale_price=Decimal("139999"),
        ),
    )
    base.update(overrides)
    return PipelineState(**base)


def test_successful_run_is_marked_ready_for_qa():
    update = _final_state_to_product_update(_state(csv_row={"SKU": "KLU-12B03S"}))
    assert update["status"] == "ready_for_qa"
    assert update["ready_for_qa_at"], "the QA clock must start, it feeds Avg QA Time"


def test_failed_run_is_marked_manual_review_with_its_reason():
    state = _state(
        manual_review_required=True,
        failure=FailureInfo(category="warranty_conflict", detail="supplied 10y, source says 1y"),
    )
    update = _final_state_to_product_update(state)
    assert update["status"] == "manual_review"
    assert update["failure_reason"] == "warranty_conflict"
    assert "1y" in update["failure_detail"]["detail"]


def test_run_without_csv_or_failure_is_marked_failed():
    """Neither output nor a reason means something went wrong silently."""
    assert _final_state_to_product_update(_state())["status"] == "failed"


def test_content_fields_are_persisted():
    state = _state(
        csv_row={"SKU": "X"},
        name="Kenwood 1 Ton KLU-12B03S AC",
        short_description="<p>short</p>",
        description="<div>long</div>",
        specs_table_html="<table></table>",
        rank_math_focus_keyword="Kenwood 1 Ton KLU-12B03S AC",
        rank_math_title="Kenwood 1 Ton KLU-12B03S AC | Buy Smart",
        resolved_warranty_phrase="1 Year Warranty",
    )
    update = _final_state_to_product_update(state)
    for field in ("name", "short_description", "description", "specs_table_html",
                  "rank_math_focus_keyword", "rank_math_title", "resolved_warranty_phrase"):
        assert update[field], f"{field} must be persisted, not dropped"


def test_dimensions_are_persisted():
    state = _state(csv_row={"SKU": "X"},
                   dimensions=DimensionsResult(weight_kg=30.0, length_cm=80.0,
                                               width_cm=30.0, height_cm=55.0))
    update = _final_state_to_product_update(state)
    assert update["weight_kg"] == 30.0
    assert update["height_cm"] == 55.0


def test_variant_flag_and_retry_count_are_persisted():
    """
    variant_shaped has a real column but was previously dropped by the state
    schema, so variant detections were silently lost.
    """
    state = _state(csv_row={"SKU": "X"}, variant_shaped=True, retry_count=3)
    update = _final_state_to_product_update(state)
    assert update["variant_shaped"] is True
    assert update["retry_count"] == 3


def test_price_discrepancy_is_persisted():
    state = _state(csv_row={"SKU": "X"}, price_discrepancy_pct=18.5)
    assert _final_state_to_product_update(state)["price_discrepancy_pct"] == 18.5


def test_manual_review_does_not_start_the_qa_clock():
    """Only a product that reached QA should count toward Avg QA Time."""
    state = _state(manual_review_required=True,
                   failure=FailureInfo(category="other", detail="x"))
    assert "ready_for_qa_at" not in _final_state_to_product_update(state)
