"""
Bulk import endpoint (POST /api/batches/bulk) and its WooCommerce-style guard.

Locks: ADD/UPDATE rows are inserted in one call; when update_existing is off,
rows carrying an existing_id are skipped (and audited) rather than overwriting a
live product; an all-skipped batch does not start a pointless run.
"""
from decimal import Decimal
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from starlette.background import BackgroundTasks

from app.api.routes import batches
from app.api.routes.batches import BulkBatchRequest, create_batch_bulk
from app.models.raw_input import RawProductInput


def _row(**overrides) -> RawProductInput:
    base = {
        "sku": "WF-6807", "model_number": "WF-6807", "brand_name": "Westpoint",
        "category_name": "Air conditioner", "product_type": "Air conditioner",
        "regular_price": Decimal(6400), "sale_price": Decimal(6400),
    }
    base.update(overrides)
    return RawProductInput(**base)


@pytest.fixture
def wired(monkeypatch):
    bid = uuid4()
    monkeypatch.setattr(batches.batches_repo, "create_batch", AsyncMock(return_value=bid))

    async def fake_create_many(rows):
        return rows  # length is what the endpoint reports as created_count

    monkeypatch.setattr(batches.products_repo, "create_many", fake_create_many)
    audit = AsyncMock()
    monkeypatch.setattr(batches.audit_repo, "log_event", audit)
    return bid, audit


@pytest.mark.asyncio
async def test_update_existing_off_skips_and_audits_id_rows(wired):
    _bid, audit = wired
    bt = BackgroundTasks()
    payload = BulkBatchRequest(
        label="mixed",
        rows=[_row(existing_id="10874"), _row(sku="NEW-1")],
        update_existing=False,
    )
    result = await create_batch_bulk(payload, bt)
    assert result.created_count == 1     # only the no-id (ADD) row
    assert result.skipped == 1
    audit.assert_awaited_once()          # the bypassed id row is audited
    assert len(bt.tasks) == 1            # a run is scheduled for the created row


@pytest.mark.asyncio
async def test_update_existing_on_processes_id_rows(wired):
    _bid, audit = wired
    bt = BackgroundTasks()
    payload = BulkBatchRequest(
        label="update",
        rows=[_row(existing_id="10874"), _row(sku="NEW-1")],
        update_existing=True,
    )
    result = await create_batch_bulk(payload, bt)
    assert result.created_count == 2
    assert result.skipped == 0
    audit.assert_not_awaited()


def test_empty_bulk_request_is_rejected():
    # An empty import is a client error, caught at the schema before any batch is made.
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        BulkBatchRequest(label="empty", rows=[])


@pytest.mark.asyncio
async def test_all_skipped_batch_does_not_run(wired):
    _bid, _audit = wired
    bt = BackgroundTasks()
    payload = BulkBatchRequest(
        label="all-id",
        rows=[_row(existing_id="1"), _row(existing_id="2")],
        update_existing=False,
    )
    result = await create_batch_bulk(payload, bt)
    assert result.created_count == 0
    assert result.skipped == 2
    assert len(bt.tasks) == 0            # nothing to process -> no run scheduled
