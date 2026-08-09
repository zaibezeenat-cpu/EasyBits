"""
The batch model has always had total_products/succeeded_count/failed_count/
manual_review_count, and the Dashboard's Recent Batches table has always
rendered them -- but nothing ever wrote them, so every batch showed 0/0/0
regardless of outcome. These tests prove the write side: the right tally is
computed and persisted via batches_repo.finish(), a short plain-English
summary is sent over SSE, and a budget-paused batch is left paused rather
than immediately overwritten with "completed" (a pre-existing bug found
while fixing this).
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.graph import batch_processor as bp

_VALID_RAW_INPUT = {
    "sku": "X", "model_number": "M", "brand_name": "B", "category_name": "C",
    "product_type": "T", "regular_price": 100, "sale_price": 90,
}


def _product() -> SimpleNamespace:
    return SimpleNamespace(id=uuid4(), raw_input=_VALID_RAW_INPUT)


async def _fake_run_batch(monkeypatch, statuses: list[str], *, budget_ok: bool = True):
    """
    Runs BatchProcessor.run_batch for len(statuses) products, faking
    _final_state_to_product_update to return each given terminal status in
    turn -- so this exercises run_batch's real tally/finish/SSE logic without
    needing a real pipeline run. Returns (finish_mock, notify_mock).
    """
    products = [_product() for _ in statuses]
    status_iter = iter(statuses)

    monkeypatch.setattr(bp.batches_repo, "get", AsyncMock(return_value=SimpleNamespace(id=uuid4())))
    monkeypatch.setattr(bp.batches_repo, "update_status", AsyncMock())
    finish_mock = AsyncMock()
    monkeypatch.setattr(bp.batches_repo, "finish", finish_mock)
    monkeypatch.setattr(bp.products_repo, "get_by_batch", AsyncMock(return_value=products))
    monkeypatch.setattr(bp.products_repo, "update_product", AsyncMock())
    monkeypatch.setattr(bp, "check_budget_ok", AsyncMock(return_value=budget_ok))
    monkeypatch.setattr(bp.settings, "LLM_INTER_PRODUCT_DELAY_SECONDS", 0)
    monkeypatch.setattr(bp, "shutdown_browser", AsyncMock())
    notify_mock = MagicMock()
    monkeypatch.setattr(bp.sse_manager, "notify", notify_mock)

    # The pipeline itself is irrelevant here -- only the STATUS
    # _final_state_to_product_update maps a finished run onto matters for the
    # tally, so that mapping function is faked directly. ainvoke echoes back
    # the (already-valid) PipelineState it was given, so run_batch's
    # isinstance check passes and model_validate is never reached.
    monkeypatch.setattr(bp.pipeline, "ainvoke", AsyncMock(side_effect=lambda state: state))
    monkeypatch.setattr(
        bp, "_final_state_to_product_update",
        lambda final_state: {"status": next(status_iter)},
    )

    await bp.BatchProcessor.run_batch(uuid4())
    return finish_mock, notify_mock


@pytest.mark.asyncio
async def test_finish_is_called_with_the_correct_tally(monkeypatch):
    finish_mock, _ = await _fake_run_batch(
        monkeypatch, ["ready_for_qa", "ready_for_qa", "manual_review", "failed"]
    )

    finish_mock.assert_called_once()
    kwargs = finish_mock.call_args.kwargs
    assert kwargs["total_products"] == 4
    assert kwargs["succeeded_count"] == 2
    assert kwargs["manual_review_count"] == 1
    assert kwargs["failed_count"] == 1
    assert kwargs["status"] == "completed_with_failures"


@pytest.mark.asyncio
async def test_all_succeeded_batch_is_plain_completed(monkeypatch):
    finish_mock, _ = await _fake_run_batch(monkeypatch, ["ready_for_qa", "ready_for_qa"])
    kwargs = finish_mock.call_args.kwargs
    assert kwargs["status"] == "completed"
    assert kwargs["failed_count"] == 0


@pytest.mark.asyncio
async def test_batch_completed_event_carries_a_short_summary(monkeypatch):
    _, notify_mock = await _fake_run_batch(monkeypatch, ["ready_for_qa", "manual_review"])

    completed_calls = [
        call for call in notify_mock.call_args_list
        if call.args[1].get("event") == "batch_completed"
    ]
    assert len(completed_calls) == 1
    payload = completed_calls[0].args[1]
    assert payload["succeeded"] == 1
    assert payload["manual_review"] == 1
    assert payload["failed"] == 0
    assert "1 ready for QA" in payload["summary"]
    assert "1 need manual review" in payload["summary"]


@pytest.mark.asyncio
async def test_budget_pause_does_not_get_overwritten_to_completed(monkeypatch):
    """
    Regression: run_batch used to unconditionally write "completed" and fire
    "batch_completed" after the loop, even when the loop broke on the budget
    guard -- silently overwriting the "paused_budget_exceeded" status it had
    just set. A paused batch must stay paused, with no completion event.
    """
    finish_mock, notify_mock = await _fake_run_batch(monkeypatch, ["ready_for_qa"], budget_ok=False)

    assert any(
        call.args[1] == {"event": "batch_paused", "reason": "budget_exceeded"}
        for call in notify_mock.call_args_list
    )
    assert not any(
        call.args[1].get("event") == "batch_completed" for call in notify_mock.call_args_list
    ), "a paused batch must not also fire batch_completed"
    finish_mock.assert_not_called()
