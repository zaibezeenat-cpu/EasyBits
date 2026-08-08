from langgraph.graph import END, StateGraph

from app.graph.nodes import (
    csv_row_assembler_node,
    deterministic_builders_node,
    duplicate_sku_guard_node,
    escalation_handler,
    extractor_node,
    html_sanitize_node,
    image_fallback_node,
    intake_triage,
    reviewer_node,
    writer_node,
)
from app.graph.router import (
    after_duplicate_sku_router,
    after_extractor_router,
    after_intake_router,
    after_review_router,
    after_writer_router,
)
from app.graph.state import PipelineState


def create_pipeline():
    workflow = StateGraph(PipelineState)

    # Define nodes
    workflow.add_node("intake_triage", intake_triage)
    workflow.add_node("extractor_node", extractor_node)
    workflow.add_node("image_fallback_node", image_fallback_node)
    workflow.add_node("writer_node", writer_node)
    workflow.add_node("reviewer_node", reviewer_node)
    workflow.add_node("escalation_handler", escalation_handler)
    workflow.add_node("deterministic_builders_node", deterministic_builders_node)
    workflow.add_node("html_sanitize_node", html_sanitize_node)
    workflow.add_node("duplicate_sku_guard_node", duplicate_sku_guard_node)
    workflow.add_node("csv_row_assembler_node", csv_row_assembler_node)

    # Define edges
    workflow.set_entry_point("intake_triage")

    # BUG FIX (Phase 3 integration test): this was an unconditional edge. Every
    # one of intake_triage's failure branches (brand/category not found, brand
    # casing mismatch, missing category schema, variant-shaped) leaves
    # category_schema as None, but extractor_node unconditionally dereferences
    # state.category_schema.fields -- an intake failure crashed the whole graph
    # with an unhandled AttributeError instead of routing to Manual Review, and
    # batch_processor's outer except just logged and skipped the product,
    # silently vanishing it (never persisted, never in the review queue).
    workflow.add_conditional_edges(
        "intake_triage",
        after_intake_router,
        {
            "escalation": "escalation_handler",
            "extractor": "extractor_node"
        }
    )

    workflow.add_conditional_edges(
        "extractor_node",
        after_extractor_router,
        {
            "escalation": "escalation_handler",
            "image_fallback": "image_fallback_node"
        }
    )
    
    workflow.add_edge("image_fallback_node", "writer_node")
    # Conditional, not a plain edge: writer_node has four failure branches and
    # reviewer_node dereferences state.writer_output unconditionally, so a plain
    # edge turned every writer failure into an AttributeError that buried the
    # real reason. Same shape as every other node that can fail.
    workflow.add_conditional_edges(
        "writer_node",
        after_writer_router,
        {
            "escalation": "escalation_handler",
            "reviewer": "reviewer_node",
        }
    )
    
    workflow.add_conditional_edges(
        "reviewer_node",
        after_review_router,
        {
            "builders": "deterministic_builders_node",
            "writer": "writer_node",
            "escalation": "escalation_handler"
        }
    )
    
    workflow.add_edge("deterministic_builders_node", "html_sanitize_node")
    workflow.add_edge("html_sanitize_node", "duplicate_sku_guard_node")
    workflow.add_conditional_edges(
        "duplicate_sku_guard_node",
        after_duplicate_sku_router,
        {
            "escalation": "escalation_handler",
            "assembler": "csv_row_assembler_node",
        }
    )
    workflow.add_edge("csv_row_assembler_node", END)
    workflow.add_edge("escalation_handler", END)

    return workflow.compile()

pipeline = create_pipeline()
