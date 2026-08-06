from uuid import UUID

from app.api.routes.products import build_product_row
from app.db.repositories.audit import audit_repo
from app.db.repositories.batches import batches_repo
from app.db.repositories.products import products_repo
from app.graph.batch_processor import BatchProcessor
from app.models.batch import Batch
from app.models.raw_input import RawProductInput
from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel, Field

router = APIRouter()


class BulkBatchRequest(BaseModel):
    label: str
    # At least one row -- an empty bulk import is a client error (422), not a
    # silently-created empty batch.
    rows: list[RawProductInput] = Field(min_length=1)
    # WooCommerce-importer-style guard: when False, rows carrying an existing_id
    # are SKIPPED rather than regenerated, so an accidental upload cannot overwrite
    # live products. When True (default), existing_id rows are updated in place.
    update_existing: bool = True


class BulkBatchResult(BaseModel):
    batch_id: UUID
    created_count: int
    skipped: int

@router.get("/", response_model=list[Batch])
async def list_batches():
    """Recent Batches, ordered newest first — used by the Dashboard and Batches page."""
    return await batches_repo.list_recent()

@router.post("/")
async def create_batch(label: str, background_tasks: BackgroundTasks, auto_run: bool = True):
    """
    auto_run=True (default): existing "New Batch" behavior — creates and immediately
    triggers processing. auto_run=False: used by Quick-Add, which needs to insert the
    product row *before* processing starts (avoids a race where the batch runs with
    zero products because none had been created yet) -- caller must explicitly hit
    POST /{batch_id}/run once the product is in place.
    """
    batch_id = await batches_repo.create_batch(label)
    if auto_run:
        background_tasks.add_task(BatchProcessor.run_batch, batch_id)
    return {"batch_id": batch_id, "status": "processing" if auto_run else "pending"}

@router.post("/bulk", response_model=BulkBatchResult)
async def create_batch_bulk(
    payload: BulkBatchRequest, background_tasks: BackgroundTasks
) -> BulkBatchResult:
    """
    Bulk import: create one batch from many pasted rows and run it once.

    ADD vs UPDATE is auto-detected per row from `existing_id` (present -> the CSV's
    ID column is filled so WooCommerce updates in place; absent -> a new product).
    A single request may mix both. With `update_existing=False`, existing_id rows
    are skipped (and audited), never touched.

    Products are inserted in one round-trip, then the pipeline runs in the
    background -- so a 50-100 row paste is a single request with no insert/run race.
    """
    batch_id = await batches_repo.create_batch(payload.label)

    eligible: list[RawProductInput] = []
    skipped = 0
    for row in payload.rows:
        if row.existing_id and not payload.update_existing:
            skipped += 1
            # Audit each bypassed product so there is a record of what was
            # intentionally not overwritten (edge case #5).
            await audit_repo.log_event(
                batch_id=str(batch_id),
                event_type="bulk_update_skipped",
                payload={"existing_id": row.existing_id, "sku": row.sku},
                actor="operator",
            )
            continue
        eligible.append(row)

    created = await products_repo.create_many(
        [build_product_row(batch_id, row) for row in eligible]
    )

    # Only run if at least one product was actually created; an all-skipped batch
    # would otherwise "complete" having processed nothing.
    if created:
        background_tasks.add_task(BatchProcessor.run_batch, batch_id)

    return BulkBatchResult(batch_id=batch_id, created_count=len(created), skipped=skipped)


@router.get("/{batch_id}")
async def get_batch(batch_id: UUID):
    batch = await batches_repo.get(batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")
    return batch

@router.post("/{batch_id}/run")
async def run_batch(batch_id: UUID, background_tasks: BackgroundTasks):
    """Manually (re)trigger processing for an existing batch, e.g. one left in
    'pending' or 'paused_budget_exceeded' — used by the batch detail page's
    Run Batch button."""
    batch = await batches_repo.get(batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")
    background_tasks.add_task(BatchProcessor.run_batch, batch_id)
    return {"batch_id": batch_id, "status": "processing"}
