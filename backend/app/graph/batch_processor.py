import asyncio
import logging
from datetime import UTC, datetime
from uuid import UUID

from app.core.budget_guard import check_budget_ok
from app.core.config import settings
from app.db.repositories.batches import batches_repo
from app.db.repositories.products import products_repo
from app.graph.pipeline import pipeline
from app.graph.state import PipelineState
from app.scraping.playwright_client import shutdown_browser
from app.sse import sse_manager

logger = logging.getLogger(__name__)


def _issue_reason(update: dict, final_state: PipelineState) -> str | None:
    """
    The real, specific reason THIS product needs attention, or None if it
    doesn't -- owner-directed (2026-08-09): the end-of-batch report must
    name the actual product and the actual issue, never a bare "check the
    review queue" or a generic "Unknown error" fallback.

    Covers all three ways a product can need a second look:
      - manual_review: the escalation reason already on state.failure.
      - ready_for_qa but review_result.passed is False: it shipped anyway
        (see after_review_router) -- name the specific failed check(s).
      - failed: whatever exception or guard rejected it.
    A clean ready_for_qa with review_result.passed True (or no review_result
    at all, e.g. a manual-review escalation that never reached the writer)
    returns None -- nothing to report.
    """
    status = update.get("status")
    if status == "manual_review" or status == "failed":
        reason = update.get("failure_reason") or "other"
        detail = (update.get("failure_detail") or {}).get("detail") or "no further detail recorded"
        return f"{reason}: {detail}"

    if status == "ready_for_qa" and final_state.review_result and final_state.review_result.passed is False:
        failed_checks = [c.detail for c in final_state.review_result.checks if not c.passed]
        if not failed_checks:
            failed_checks = [final_state.review_result.failure_summary or "did not pass review"]
        return "shipped without passing every SEO/fact check: " + "; ".join(failed_checks)

    return None


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
        update["ready_for_qa_at"] = datetime.now(UTC).isoformat()

    return update

class BatchProcessor:
    @staticmethod
    async def run_batch(batch_id: UUID):
        batch = await batches_repo.get(batch_id)
        if not batch:
            return

        await batches_repo.update_status(batch_id, "processing")
        products = await products_repo.get_by_batch(batch_id)

        try:
            tally, paused, issues = await BatchProcessor._run_products(batch_id, products)
        finally:
            # The scraper's shared Chromium is a real OS process that outlives
            # this coroutine if nothing closes it. In `finally` so a crash or a
            # cancelled batch cannot leave a browser running.
            await shutdown_browser()

        # BUG FIX: this used to unconditionally write "completed" and fire
        # "batch_completed" even when the loop broke on the budget guard --
        # overwriting the "paused_budget_exceeded" status it had JUST set,
        # and sending a contradictory "completed" event right after "paused".
        # A paused batch stays paused; only a batch that actually ran every
        # product to the end gets a completion summary.
        if paused:
            return

        status = "completed_with_failures" if tally["failed"] else "completed"
        await batches_repo.finish(
            batch_id,
            status=status,
            total_products=len(products),
            succeeded_count=tally["succeeded"],
            failed_count=tally["failed"],
            manual_review_count=tally["manual_review"],
        )

        # The short end-of-batch summary: what the operator actually wants to
        # know without opening the batch -- how many are ready to export vs.
        # need attention. Logged server-side and sent over SSE so the
        # frontend's completion toast (batches/[id]/page.tsx) can show the
        # real numbers instead of a bare "Batch completed".
        summary = (
            f"{tally['succeeded']} ready for QA, "
            f"{tally['manual_review']} need manual review, "
            f"{tally['failed']} failed"
        )

        # 2026-08-09 (owner-directed): "if failed or issue with product, pass
        # it, but at the end strictly tell me what the issue was -- not
        # 'check the review queue', not 'unknown error'." Every product with
        # a real issue -- manual_review, shipped-but-failed-SEO, or a hard
        # failure -- gets its SKU and the ACTUAL reason spelled out here, not
        # a redirect. Full list always goes to the server log; the SSE
        # payload (and the toast built from it) caps at 5 named entries plus
        # a count, since a 50-line toast is unreadable, but the full list is
        # always in `issues` for the batch detail page to render in full.
        issue_lines = [
            f"{i.get('sku') or i.get('name') or 'unknown SKU'}: {i['reason']}"
            for i in issues
        ]
        if issue_lines:
            logger.info(f"Batch {batch_id} issues ({len(issue_lines)}):\n" + "\n".join(issue_lines))
            shown = issue_lines[:5]
            more = len(issue_lines) - len(shown)
            summary += "\nIssues:\n- " + "\n- ".join(shown)
            if more > 0:
                summary += f"\n- +{more} more (see the batch page for the full list)"

        logger.info(f"Batch {batch_id} complete: {tally['succeeded']} ready for QA, "
                    f"{tally['manual_review']} manual review, {tally['failed']} failed")
        sse_manager.notify(str(batch_id), {
            "event": "batch_completed",
            "total": len(products),
            "succeeded": tally["succeeded"],
            "manual_review": tally["manual_review"],
            "failed": tally["failed"],
            "issues": issues,
            "summary": summary,
        })

    @staticmethod
    async def _run_products(batch_id: UUID, products: list) -> tuple[dict[str, int], bool, list[dict]]:
        """
        Runs every product's pipeline, bounded by settings.BATCH_CONCURRENCY.

        BATCH_CONCURRENCY=1 (the default) preserves the original serial
        behaviour: asyncio.Semaphore(1) admits exactly one worker at a time,
        in submission order. Raising it is what actually cuts batch
        wall-clock time -- but the concurrency-SAFE pieces this depends on
        (the per-provider LLM semaphore in llm_provider.py, the Playwright
        context semaphore, the locks on the two quota caches in
        source_discovery.py) all live elsewhere; this method only adds the
        product-level fan-out on top of them.

        Tally counting (`tally["x"] += 1`) is safe without a lock: Python's
        asyncio is single-threaded and cooperative, and nothing here awaits
        between reading and writing a tally value, so no other coroutine can
        interleave mid-increment.
        """
        tally = {"succeeded": 0, "failed": 0, "manual_review": 0}
        # Every product with a real, nameable issue -- {sku, name, status,
        # reason} -- built by _issue_reason() so the end-of-batch report can
        # name each one specifically instead of pointing at the queue.
        issues: list[dict] = []
        semaphore = asyncio.Semaphore(max(1, settings.BATCH_CONCURRENCY))
        # Concurrency-safe "pause once" latch: several workers can discover
        # the budget is exceeded at roughly the same time, but the batch
        # must be marked paused, and the SSE event fired, exactly once.
        pause_lock = asyncio.Lock()
        pause_state = {"paused": False, "notified": False}

        async def _mark_paused() -> None:
            async with pause_lock:
                if pause_state["notified"]:
                    return
                pause_state["notified"] = True
                pause_state["paused"] = True
            logger.warning(f"Budget exceeded. Pausing batch {batch_id}")
            await batches_repo.update_status(batch_id, "paused_budget_exceeded")
            sse_manager.notify(str(batch_id), {"event": "batch_paused", "reason": "budget_exceeded"})

        async def _process_one(product) -> None:
            async with semaphore:
                if pause_state["paused"]:
                    return

                # 1. Budget Guard Check -- re-checked per worker (not once for
                # the whole batch) so a mid-batch overrun under concurrency is
                # still caught before MORE products start, not just the next
                # one in a single queue.
                if not await check_budget_ok():
                    await _mark_paused()
                    return
                if pause_state["paused"]:
                    # Another worker paused the batch while this one awaited
                    # the budget check above.
                    return

                # 2. Pacing delay (see settings.LLM_INTER_PRODUCT_DELAY_SECONDS).
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

                    if update["status"] == "ready_for_qa":
                        tally["succeeded"] += 1
                    elif update["status"] == "manual_review":
                        tally["manual_review"] += 1
                    else:
                        tally["failed"] += 1

                    reason = _issue_reason(update, final_state)
                    if reason:
                        issues.append({
                            "sku": product.raw_input.get("sku") if isinstance(product.raw_input, dict) else None,
                            "name": update.get("name"),
                            "status": update["status"],
                            "reason": reason,
                        })

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
                    tally["failed"] += 1
                    issues.append({
                        "sku": product.raw_input.get("sku") if isinstance(product.raw_input, dict) else None,
                        "name": None,
                        "status": "failed",
                        "reason": f"pipeline_exception: {e!s}",
                    })
                    sse_manager.notify(str(batch_id), {
                        "event": "product_failed",
                        "product_id": str(product.id),
                        "error": str(e)
                    })

        # return_exceptions=True: _process_one already catches everything
        # relevant to ONE product internally, but this is the outer isolation
        # net -- an unexpected error here (e.g. a DB call outside the inner
        # try) must not cancel every other in-flight product.
        results = await asyncio.gather(
            *(_process_one(product) for product in products), return_exceptions=True
        )
        for product, result in zip(products, results, strict=False):
            if isinstance(result, Exception):
                logger.error(f"Unhandled error processing product {product.id}: {result}")
                tally["failed"] += 1
                issues.append({
                    "sku": product.raw_input.get("sku") if isinstance(product.raw_input, dict) else None,
                    "name": None,
                    "status": "failed",
                    "reason": f"pipeline_exception (outer): {result!s}",
                })

        return tally, pause_state["paused"], issues
