from app.graph.state import PipelineState


def after_intake_router(state: PipelineState) -> str:
    """
    intake_triage's failure branches never set category_schema, and
    extractor_node unconditionally reads state.category_schema.fields --
    route straight to escalation on any intake failure so that dereference
    never happens (see pipeline.py's comment on this edge).
    """
    if state.failure or not state.category_schema:
        return "escalation"
    return "extractor"

def after_extractor_router(state: PipelineState) -> str:
    if state.failure:
        return "escalation"
    if not state.extraction:
        return "escalation"

    # 2026-08-09 (owner-directed): a field no source states is skipped, not
    # escalated -- specs_renderer/name_builder/etc. already tolerate a None
    # confirmed_value (rendered as "Not Available" / dropped from the title).
    # Only a genuine cross-source DISAGREEMENT still blocks the product --
    # that's the one case where publishing could put a wrong fact on the
    # live store, versus a merely-incomplete one.
    if state.extraction.conflicting_fields(state.category_schema):
        return "escalation"

    return "image_fallback"

def after_writer_router(state: PipelineState) -> str:
    """
    writer_node has four failure branches -- brand/category gone missing since
    intake, no warranty phrase configured, the LLM call raising, and the SEO
    guards -- and every one returns a clean FailureInfo. Without this router the
    graph ran reviewer_node anyway, which dereferences state.writer_output and
    raised AttributeError on None, so the writer's real reason was replaced by a
    traceback and escalation_handler never filed the product.

    The writer_output check is not redundant with the failure check: it also
    covers a node that returns a partial state without flagging it.
    """
    if state.failure or state.manual_review_required:
        return "escalation"
    if not state.writer_output:
        return "escalation"
    return "reviewer"


def after_duplicate_sku_router(state: PipelineState) -> str:
    """
    A colliding SKU is already doomed -- assembling its CSV row wastes the work
    and persists a csv_row for a product that must never be exported. Contained
    before this existed (manual_review_required maps to status="manual_review",
    so it never reached the file) but the row should not be built at all.
    """
    if state.failure or state.manual_review_required:
        return "escalation"
    return "assembler"


def after_review_router(state: PipelineState) -> str:
    """Retry logic: exactly 3 total attempts (Phase 2 §3.3)"""
    if state.manual_review_required or state.failure:
        return "escalation"

    if state.review_result and state.review_result.passed:
        return "builders"
    
    # writer_node increments retry_count BEFORE reviewer runs, so by the time this
    # router checks, retry_count already reflects "attempts made so far":
    # attempt 1 -> retry_count=1 -> 1<3 -> writer (attempt 2)
    # attempt 2 -> retry_count=2 -> 2<3 -> writer (attempt 3)
    # attempt 3 -> retry_count=3 -> 3<3 false -> escalation
    # This gives exactly 3 total Writer/Reviewer attempts (was capped at 2 — off-by-one, fixed).
    if state.retry_count < 3:
        return "writer"

    return "escalation"
