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
    
    # Check for conflicts or missing required fields
    if state.extraction.conflicting_fields(state.category_schema) or \
       state.extraction.missing_required_fields(state.category_schema):
        return "escalation"
        
    return "image_fallback"

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
