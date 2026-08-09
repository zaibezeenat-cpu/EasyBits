from decimal import Decimal
from uuid import uuid4

from app.graph.router import after_review_router
from app.graph.state import PipelineState
from app.models.raw_input import RawProductInput
from app.models.review_result import ReviewResult


def get_dummy_raw_input():
    return RawProductInput(
        sku="SKU1",
        model_number="M1",
        brand_name="B1",
        category_name="C1",
        product_type="T1",
        regular_price=Decimal(100),
        sale_price=Decimal(90)
    )

def test_after_review_router_retry_logic():
    state = PipelineState(
        product_id=uuid4(),
        batch_id=uuid4(),
        raw_input=get_dummy_raw_input(),
        retry_count=0,
        review_result=ReviewResult(
            passed=False, 
            preflight_score=50,
            checks=[], 
            warranty_consistent=False,
            fact_cross_check_passed=False,
            fact_cross_check_notes=[],
            failure_summary="Failed"
        )
    )
    
    # Up to 3 total Writer/Reviewer attempts: retry_count=1 and 2 both retry.
    # (Was capped at 2 attempts — off-by-one bug, fixed.) 2026-08-09
    # (owner-directed): retry_count=3 now ships to "builders" instead of
    # escalating -- retry exhaustion is no longer a Manual Review reason.
    state.retry_count = 1
    assert after_review_router(state) == "writer"

    state.retry_count = 2
    assert after_review_router(state) == "writer"

    state.retry_count = 3
    assert after_review_router(state) == "builders"

def test_after_review_router_success():
    state = PipelineState(
        product_id=uuid4(),
        batch_id=uuid4(),
        raw_input=get_dummy_raw_input(),
        retry_count=1,
        review_result=ReviewResult(
            passed=True, 
            preflight_score=95,
            checks=[],
            warranty_consistent=True,
            fact_cross_check_passed=True,
            fact_cross_check_notes=[]
        )
    )
    assert after_review_router(state) == "builders"

def test_after_review_router_immediate_escalation():
    state = PipelineState(
        product_id=uuid4(),
        batch_id=uuid4(),
        raw_input=get_dummy_raw_input(),
        manual_review_required=True
    )
    assert after_review_router(state) == "escalation"
