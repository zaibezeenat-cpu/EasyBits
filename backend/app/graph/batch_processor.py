import asyncio
import logging
from datetime import datetime, timezone
from uuid import UUID
from app.graph.pipeline import pipeline
from app.graph.state import PipelineState
from app.core.config import settings
from app.core.budget_guard import check_budget_ok
from app.sse import sse_manager
from app.db.repositories.products import products_repo
from app.db.repositories.batches import batches_repo

logger = logging.getLogger(__name__)


def _final_state_to_product_update(final_state: PipelineState) -> dict:
    """
    Maps the graph's final PipelineState onto `products` columns.

    BUG FIX (Phase 3 integration test): the pipeline computed a fully correct
    result -- name, description, specs, CSV row, review scores -- and this
    function's absence meant `run_batch` threw all of it away the moment
    `pipeline.ainvoke()` returned, only ever firing an SSE notification.
    Nothing was ever persisted, so the QA Panel/CSV export/dashboard had
    nothing real to show no matter how correct the in-memory result was.
    """
    if final_state.manual_review_required or final_state.failure:
        status = "manual_review"
    elif final_state.csv_row:
        status = "ready_for_qa"
    else:
        status = "failed"

    update: dict = {
        "status": status,
        "retry_count": final_state.retry_count,
        "variant_shaped": final_state.variant_shaped,
        "name": final_state.name,
        "short_description": final_state.short_description,
        "description": final_state.description,
        "specs_table_html": final_state.specs_table_html,
        "rank_math_focus_keyword": final_state.rank_math_focus_keyword,
        "rank_math_title": final_state.rank_math_title,
        "resolved_warranty_phrase": final_state.resolved_warranty_phrase,
        "price_discrepancy_pct": final_state.price_discrepancy_pct,
        "csv_row": final_state.csv_row or {},
    }

    if final_state.writer_output:
        update["writer_result"] = final_state.writer_output.model_dump(mode="json")
        update["rank_math_description"] = final_state.writer_output.rank_math_description
    if final_state.extraction:
        update["extraction_result"] = final_state.extraction.model_dump(mode="json")
    if final_state.review_result:
        update["review_result"] = final_state.review_result.model_dump(mode="json")
        update["preflight_score"] = final_state.review_result.preflight_score
    if final_state.dimensions:
        update["weight_kg"] = final_state.dimensions.weight_kg
        update["length_cm"] = final_state.dimensions.length_cm
        update["width_cm"] = final_state.dimensions.width_cm
        update["height_cm"] = final_state.dimensions.height_cm
    if final_state.failure:
        update["failure_reason"] = final_state.failure.category
        update["failure_detail"] = {"detail": final_state.failure.detail}
    if status == "ready_for_qa":
        update["ready_for_qa_at"] = datetime.now(timezone.utc).isoformat()

    return update

class BatchProcessor:
    @staticmethod
    async def run_batch(batch_id: UUID):
        batch = await batches_repo.get(batch_id)
        if not batch:
            return

        await batches_repo.update_status(batch_id, "processing")
        products = await products_repo.get_by_batch(batch_id)
        
        for product in products:
            # 1. Budget Guard Check
            if not await check_budget_ok():
                logger.warning(f"Budget exceeded. Pausing batch {batch_id}")
                await batches_repo.update_status(batch_id, "paused_budget_exceeded")
                sse_manager.notify(str(batch_id), {"event": "batch_paused", "reason": "budget_exceeded"})
                break

            # 2. Sequential Delay
            await asyncio.sleep(settings.LLM_INTER_PRODUCT_DELAY_SECONDS)

            # 3. Process Product
            try:
                from app.models.raw_input import RawProductInput
                raw_input_data = product.raw_input or {}
                raw_input = RawProductInput.model_validate(raw_input_data)

                state = PipelineState(
                    product_id=product.id,
                    batch_id=batch_id,
                    raw_input=raw_input
                )
                
                # Execute pipeline
                raw_final_state = await pipeline.ainvoke(state)
                # LangGraph returns the compiled state as a dict matching the
                # schema, not necessarily a PipelineState instance -- normalize
                # it so the field access below is reliable either way.
                final_state = (
                    raw_final_state if isinstance(raw_final_state, PipelineState)
                    else PipelineState.model_validate(raw_final_state)
                )

                update = _final_state_to_product_update(final_state)
                await products_repo.update_product(product.id, update)

                sse_manager.notify(str(batch_id), {
                    "event": "product_completed",
                    "product_id": str(product.id),
                    "status": update["status"]
                })
                
            except Exception as e:
                logger.error(f"Error processing product {product.id}: {e}")
                # Isolation gap fix: the per-product try/except already prevents one
                # product from crashing the whole batch, but previously the crashed
                # product was only announced over SSE and never persisted -- it stayed
                # 'pending' forever, invisible in the Review Queue. Mark it 'failed'
                # with the error so it surfaces for the operator. This DB write is
                # itself guarded: if even this fails, we still continue the batch.
                try:
                    await products_repo.update_product(product.id, {
                        "status": "failed",
                        "failure_reason": "pipeline_exception",
                        "failure_detail": {"detail": str(e)},
                    })
                except Exception as persist_err:
                    logger.error(
                        f"Could not persist failed status for product {product.id}: {persist_err}"
                    )
                sse_manager.notify(str(batch_id), {
                    "event": "product_failed",
                    "product_id": str(product.id),
                    "error": str(e)
                })
                # Isolation: continue to next product
                continue

        await batches_repo.update_status(batch_id, "completed")
        sse_manager.notify(str(batch_id), {"event": "batch_completed"})
