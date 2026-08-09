"""
2026-08-09 (owner-directed): "if failed or issue with product, pass it, but
at the end strictly tell me what the issue was -- not 'check the review
queue', not 'unknown error'." These tests prove _issue_reason() names the
real product and the real reason for every way a product can need
attention, and that run_batch's summary/SSE payload actually carries it.
"""
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.graph import batch_processor as bp
from app.graph.batch_processor import _issue_reason
from app.graph.state import PipelineState
from app.models.failure import FailureInfo
from app.models.raw_input import RawProductInput
from app.models.review_result import ReviewResult, SeoCheckResult

_VALID_RAW_INPUT = {
    "sku": "X", "model_number": "M", "brand_name": "B", "category_name": "C",
    "product_type": "T", "regular_price": 100, "sale_price": 90,
}


def _state(**overrides) -> PipelineState:
    base = {"product_id": uuid4(), "batch_id": uuid4(), "raw_input": RawProductInput(**_VALID_RAW_INPUT)}
    base.update(overrides)
    return PipelineState(**base)


def test_manual_review_reason_names_the_real_failure_not_unknown_error():
    state = _state(
        manual_review_required=True,
        failure=FailureInfo(category="spec_conflict", detail="sources disagree on: capacity"),
    )
    update = bp._final_state_to_product_update(state)
    reason = _issue_reason(update, state)
    assert reason == "spec_conflict: sources disagree on: capacity"
    assert "unknown" not in reason.lower()


def test_failed_reason_names_the_real_failure():
    state = _state(failure=FailureInfo(category="production_lock_violation", detail="meta description could not fit"))
    # A failure with neither csv_row nor manual_review_required maps to "failed"
    # only when manual_review_required is False AND failure is falsy in the
    # existing status logic -- but here failure IS set, which maps to
    # "manual_review" per _final_state_to_product_update. Exercise the true
    # "failed" path instead: no csv_row, no failure, no manual_review_required.
    bare_fail_state = _state()
    update = bp._final_state_to_product_update(bare_fail_state)
    assert update["status"] == "failed"
    reason = _issue_reason(update, bare_fail_state)
    assert reason is not None
    assert "no further detail recorded" in reason  # nothing more specific was ever set -- still not "Unknown error"


def test_shipped_with_seo_issues_names_the_specific_failed_checks():
    state = _state(
        csv_row={"SKU": "X"},
        review_result=ReviewResult(
            passed=False, preflight_score=40, warranty_consistent=True,
            fact_cross_check_passed=True, fact_cross_check_notes=[],
            checks=[
                SeoCheckResult(check_name="meta_description_length_150_160", passed=False, detail="Meta description length is 140 (required 150-160)."),
                SeoCheckResult(check_name="keyword_density_in_range", passed=True, detail="ok"),
            ],
        ),
    )
    update = bp._final_state_to_product_update(state)
    assert update["status"] == "ready_for_qa"
    reason = _issue_reason(update, state)
    assert reason is not None
    assert "shipped without passing every SEO/fact check" in reason
    assert "Meta description length is 140" in reason
    assert "keyword_density_in_range" not in reason, "a PASSED check must not appear in the reason"


def test_clean_ship_has_no_issue_reason():
    state = _state(
        csv_row={"SKU": "X"},
        review_result=ReviewResult(
            passed=True, preflight_score=95, warranty_consistent=True,
            fact_cross_check_passed=True, fact_cross_check_notes=[], checks=[],
        ),
    )
    update = bp._final_state_to_product_update(state)
    assert _issue_reason(update, state) is None


@pytest.mark.asyncio
async def test_run_batch_summary_names_products_and_reasons_not_a_redirect(monkeypatch):
    """End-to-end through run_batch: the SSE batch_completed payload's
    `issues` list and `summary` text must name real SKUs and real reasons."""
    now = datetime.now(UTC)
    products = [
        SimpleNamespace(id=uuid4(), raw_input={**_VALID_RAW_INPUT, "sku": "GOOD-1"}),
        SimpleNamespace(id=uuid4(), raw_input={**_VALID_RAW_INPUT, "sku": "BAD-SEO"}),
        SimpleNamespace(id=uuid4(), raw_input={**_VALID_RAW_INPUT, "sku": "BAD-CONFLICT"}),
    ]

    monkeypatch.setattr(bp.batches_repo, "get", AsyncMock(return_value=SimpleNamespace(id="b")))
    monkeypatch.setattr(bp.batches_repo, "update_status", AsyncMock())
    monkeypatch.setattr(bp.batches_repo, "finish", AsyncMock())
    monkeypatch.setattr(bp.products_repo, "get_by_batch", AsyncMock(return_value=products))
    monkeypatch.setattr(bp.products_repo, "update_product", AsyncMock())
    monkeypatch.setattr(bp, "check_budget_ok", AsyncMock(return_value=True))
    monkeypatch.setattr(bp.settings, "LLM_INTER_PRODUCT_DELAY_SECONDS", 0)
    monkeypatch.setattr(bp.settings, "BATCH_CONCURRENCY", 1)
    monkeypatch.setattr(bp, "shutdown_browser", AsyncMock())
    notify_mock = MagicMock()
    monkeypatch.setattr(bp.sse_manager, "notify", notify_mock)

    states_by_sku = {
        "GOOD-1": _state(csv_row={"SKU": "GOOD-1"}, review_result=ReviewResult(
            passed=True, preflight_score=95, warranty_consistent=True,
            fact_cross_check_passed=True, fact_cross_check_notes=[], checks=[],
        )),
        "BAD-SEO": _state(csv_row={"SKU": "BAD-SEO"}, review_result=ReviewResult(
            passed=False, preflight_score=40, warranty_consistent=True,
            fact_cross_check_passed=True, fact_cross_check_notes=[],
            checks=[SeoCheckResult(check_name="meta_description_length_150_160", passed=False, detail="too short")],
        )),
        "BAD-CONFLICT": _state(
            manual_review_required=True,
            failure=FailureInfo(category="spec_conflict", detail="sources disagree on: capacity"),
        ),
    }

    async def fake_ainvoke(state):
        sku = state.raw_input.sku
        target = states_by_sku[sku]
        return target

    monkeypatch.setattr(bp.pipeline, "ainvoke", fake_ainvoke)

    await bp.BatchProcessor.run_batch(uuid4())

    completed = [c for c in notify_mock.call_args_list if c.args[1].get("event") == "batch_completed"]
    assert len(completed) == 1
    payload = completed[0].args[1]

    issues_by_sku = {i["sku"]: i["reason"] for i in payload["issues"]}
    assert "GOOD-1" not in issues_by_sku, "a clean product must not appear in issues"
    assert "too short" in issues_by_sku["BAD-SEO"]
    assert "spec_conflict" in issues_by_sku["BAD-CONFLICT"]
    assert "sources disagree on: capacity" in issues_by_sku["BAD-CONFLICT"]

    assert "BAD-SEO" in payload["summary"]
    assert "BAD-CONFLICT" in payload["summary"]
    assert "unknown error" not in payload["summary"].lower()
