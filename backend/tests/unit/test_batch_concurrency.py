"""
BATCH_CONCURRENCY: default 1 preserves the original serial behaviour exactly
(proven by every existing batch_processor test passing unmodified). These
tests prove the opt-in concurrent path specifically: products actually
overlap in flight when BATCH_CONCURRENCY > 1, and a budget overrun discovered
by several concurrent workers at once still pauses the batch exactly once.
"""
import asyncio
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


@pytest.mark.asyncio
async def test_products_actually_overlap_when_concurrency_is_raised(monkeypatch):
    """With BATCH_CONCURRENCY=3, 3 products' pipeline.ainvoke calls must be
    in flight at the same time -- proving this is real concurrency, not
    just a config value that does nothing."""
    products = [_product() for _ in range(3)]

    monkeypatch.setattr(bp.batches_repo, "get", AsyncMock(return_value=SimpleNamespace(id="b")))
    monkeypatch.setattr(bp.batches_repo, "update_status", AsyncMock())
    monkeypatch.setattr(bp.batches_repo, "finish", AsyncMock())
    monkeypatch.setattr(bp.products_repo, "get_by_batch", AsyncMock(return_value=products))
    monkeypatch.setattr(bp.products_repo, "update_product", AsyncMock())
    monkeypatch.setattr(bp, "check_budget_ok", AsyncMock(return_value=True))
    monkeypatch.setattr(bp.settings, "LLM_INTER_PRODUCT_DELAY_SECONDS", 0)
    monkeypatch.setattr(bp.settings, "BATCH_CONCURRENCY", 3)
    monkeypatch.setattr(bp, "shutdown_browser", AsyncMock())
    monkeypatch.setattr(bp.sse_manager, "notify", MagicMock())
    monkeypatch.setattr(bp, "_final_state_to_product_update", lambda s: {"status": "ready_for_qa"})

    in_flight = 0
    max_in_flight = 0

    async def fake_ainvoke(state):
        nonlocal in_flight, max_in_flight
        in_flight += 1
        max_in_flight = max(max_in_flight, in_flight)
        await asyncio.sleep(0.05)
        in_flight -= 1
        return state

    monkeypatch.setattr(bp.pipeline, "ainvoke", fake_ainvoke)

    await bp.BatchProcessor.run_batch(uuid4())

    assert max_in_flight == 3, "all 3 products should have been in flight at once"


@pytest.mark.asyncio
async def test_concurrency_one_stays_fully_serial(monkeypatch):
    """The default: BATCH_CONCURRENCY=1 must never let two products'
    pipeline.ainvoke calls overlap."""
    products = [_product() for _ in range(3)]

    monkeypatch.setattr(bp.batches_repo, "get", AsyncMock(return_value=SimpleNamespace(id="b")))
    monkeypatch.setattr(bp.batches_repo, "update_status", AsyncMock())
    monkeypatch.setattr(bp.batches_repo, "finish", AsyncMock())
    monkeypatch.setattr(bp.products_repo, "get_by_batch", AsyncMock(return_value=products))
    monkeypatch.setattr(bp.products_repo, "update_product", AsyncMock())
    monkeypatch.setattr(bp, "check_budget_ok", AsyncMock(return_value=True))
    monkeypatch.setattr(bp.settings, "LLM_INTER_PRODUCT_DELAY_SECONDS", 0)
    monkeypatch.setattr(bp.settings, "BATCH_CONCURRENCY", 1)
    monkeypatch.setattr(bp, "shutdown_browser", AsyncMock())
    monkeypatch.setattr(bp.sse_manager, "notify", MagicMock())
    monkeypatch.setattr(bp, "_final_state_to_product_update", lambda s: {"status": "ready_for_qa"})

    in_flight = 0
    max_in_flight = 0

    async def fake_ainvoke(state):
        nonlocal in_flight, max_in_flight
        in_flight += 1
        max_in_flight = max(max_in_flight, in_flight)
        await asyncio.sleep(0.01)
        in_flight -= 1
        return state

    monkeypatch.setattr(bp.pipeline, "ainvoke", fake_ainvoke)

    await bp.BatchProcessor.run_batch(uuid4())

    assert max_in_flight == 1, "BATCH_CONCURRENCY=1 must remain fully serial"


@pytest.mark.asyncio
async def test_budget_pause_fires_exactly_once_under_concurrency(monkeypatch):
    """
    Several concurrent workers can all see check_budget_ok()=False at
    roughly the same time. The pause status write and the "batch_paused"
    SSE event must still happen exactly once, not once per worker.
    """
    products = [_product() for _ in range(5)]

    update_status_mock = AsyncMock()
    notify_mock = MagicMock()

    monkeypatch.setattr(bp.batches_repo, "get", AsyncMock(return_value=SimpleNamespace(id="b")))
    monkeypatch.setattr(bp.batches_repo, "update_status", update_status_mock)
    monkeypatch.setattr(bp.batches_repo, "finish", AsyncMock())
    monkeypatch.setattr(bp.products_repo, "get_by_batch", AsyncMock(return_value=products))
    monkeypatch.setattr(bp.products_repo, "update_product", AsyncMock())
    monkeypatch.setattr(bp.settings, "LLM_INTER_PRODUCT_DELAY_SECONDS", 0)
    monkeypatch.setattr(bp.settings, "BATCH_CONCURRENCY", 5)
    monkeypatch.setattr(bp, "shutdown_browser", AsyncMock())
    monkeypatch.setattr(bp.sse_manager, "notify", notify_mock)

    # Every worker sees the budget as already exceeded -- the realistic
    # "batch was already over budget before this run started" case, and the
    # one most likely to have every worker discover it simultaneously.
    monkeypatch.setattr(bp, "check_budget_ok", AsyncMock(return_value=False))

    await bp.BatchProcessor.run_batch(uuid4())

    paused_calls = [c for c in update_status_mock.call_args_list if c.args[1] == "paused_budget_exceeded"]
    assert len(paused_calls) == 1, "budget pause must be written exactly once, not once per worker"

    paused_events = [
        c for c in notify_mock.call_args_list
        if c.args[1] == {"event": "batch_paused", "reason": "budget_exceeded"}
    ]
    assert len(paused_events) == 1, "batch_paused must be sent exactly once, not once per worker"
