"""
Batch isolation: one product's pipeline exception must not crash the batch, AND
the crashed product must be persisted as `failed` so it surfaces in the queue
instead of silently staying `pending` forever.
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.graph import batch_processor as bp


@pytest.mark.asyncio
async def test_pipeline_exception_persists_failed_status_and_continues(monkeypatch):
    good_raw = {
        "sku": "X", "model_number": "M", "brand_name": "B", "category_name": "C",
        "product_type": "T", "regular_price": 100, "sale_price": 90,
    }
    p1 = SimpleNamespace(id=uuid4(), raw_input=good_raw)
    p2 = SimpleNamespace(id=uuid4(), raw_input=good_raw)

    monkeypatch.setattr(bp.batches_repo, "get", AsyncMock(return_value=SimpleNamespace(id=uuid4())))
    monkeypatch.setattr(bp.batches_repo, "update_status", AsyncMock())
    # Both products fail, but that's not a budget pause -- run_batch still
    # reaches the natural end and persists the final tally via finish().
    monkeypatch.setattr(bp.batches_repo, "finish", AsyncMock())
    monkeypatch.setattr(bp.products_repo, "get_by_batch", AsyncMock(return_value=[p1, p2]))
    monkeypatch.setattr(bp, "check_budget_ok", AsyncMock(return_value=True))
    monkeypatch.setattr(bp.settings, "LLM_INTER_PRODUCT_DELAY_SECONDS", 0)
    monkeypatch.setattr(bp.sse_manager, "notify", MagicMock())

    updates: list = []

    async def fake_update(pid, data):
        updates.append((pid, data))

    monkeypatch.setattr(bp.products_repo, "update_product", fake_update)
    # Every product's pipeline blows up -> isolation + failed-status must apply to both.
    monkeypatch.setattr(bp.pipeline, "ainvoke", AsyncMock(side_effect=Exception("boom")))

    await bp.BatchProcessor.run_batch(uuid4())

    failed = [(pid, d) for pid, d in updates if d.get("status") == "failed"]
    assert len(failed) == 2, "both crashed products must be marked failed (isolation held)"
    assert failed[0][1]["failure_reason"] == "pipeline_exception"
    assert "boom" in failed[0][1]["failure_detail"]["detail"]
