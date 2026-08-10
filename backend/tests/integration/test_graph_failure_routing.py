"""
Every node's failure return must actually reach escalation_handler.

WHY THIS EXISTS
---------------
Found by running the real graph end-to-end against the operator's own sheet,
not by a unit test -- because no unit test can see it. Each node is individually
correct: writer_node catches its exception and returns a clean FailureInfo plus
manual_review_required=True, exactly like every other node. The defect is in the
WIRING. pipeline.py joined writer_node to reviewer_node with an unconditional
add_edge, so the graph ran reviewer_node anyway, which dereferences
state.writer_output and raised AttributeError: 'NoneType' object has no
attribute 'hero_heading'.

The consequences, in order of how much they cost the operator:

  1. The real reason is lost. batch_processor's per-product try/except catches
     the AttributeError and persists failure_reason="pipeline_exception" with a
     Python traceback string. The operator reads an internal error instead of
     "No warranty phrase configured for brand X" -- which is actionable.
  2. escalation_handler never runs, so the product is never added to the manual
     review queue by the path designed to do it.

writer_node has FOUR such failure returns, and one of them fires whenever the
warranty matrix has no row and the sheet carried no warranty override -- not a
rare LLM hiccup but an ordinary data gap, on every affected row.

The same unconditional-edge shape existed on duplicate_sku_guard_node. That one
is contained (manual_review_required still maps to status="manual_review", so a
colliding SKU never reaches the CSV) but it still ran the assembler for a
product already known to be doomed, and persisted a csv_row for it.

The second test is the lock: it walks the compiled graph and fails if ANY node
that can return a failure has an unconditional outgoing edge. That is what stops
this returning the next time a node is added.
"""
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from app.graph.pipeline import pipeline
from app.graph.state import PipelineState
from app.models.extraction import ExtractionResult, SourceCitation
from app.models.raw_input import RawProductInput
from app.models.review_result import ReviewResult
from app.models.taxonomy import Brand, Category, CategorySpecSchema, SpecField
from app.models.writer_output import FAQPair, WriterOutput

NOW = datetime.now(UTC)
PARENT_ID = uuid4()

BRAND = Brand(id=uuid4(), name="Anex", is_active=True, needs_confirmation=False,
              created_at=NOW, updated_at=NOW)
CATEGORY = Category(id=uuid4(), name="Hand Chopper", parent_id=PARENT_ID, is_active=True,
                    needs_confirmation=False, created_at=NOW, updated_at=NOW)
PARENT = Category(id=PARENT_ID, name="Kitchen Appliances", parent_id=None, is_active=True,
                  needs_confirmation=False, created_at=NOW, updated_at=NOW)

SCHEMA = CategorySpecSchema(
    id=uuid4(), category_id=CATEGORY.id, created_at=NOW, updated_at=NOW,
    fields=[
        SpecField(key="brand", label="Brand", required=True),
        SpecField(key="model_number", label="Model Number", required=True),
        SpecField(key="capacity", label="Capacity", required=False),
    ],
)

SOURCE_TEXT = (
    "Anex AG-01 Handy Pull Chopper. Pull-string operated, no electricity needed. "
    "900 ml bowl with 3 stainless steel blades. 2 years warranty."
)


def _raw() -> RawProductInput:
    return RawProductInput(
        sku="AG-01", model_number="AG-01", brand_name="Anex",
        category_name="Hand Chopper", product_type="Hand Chopper",
        regular_price=Decimal(1860), sale_price=Decimal(1550),
        warranty_override="2 Years Warranty",
        official_url="https://www.anex.pk/ag-01",
    )


def _extraction() -> ExtractionResult:
    def cite(field: str, value: str) -> SourceCitation:
        return SourceCitation(
            field_name=field, value=value, source_url="https://www.anex.pk/ag-01",
            source_type="official", confidence="confirmed", fetched_at=NOW,
        )
    return ExtractionResult(
        product_id="AG-01", category_key="Hand Chopper",
        citations=[cite("brand", "Anex"), cite("model_number", "AG-01"),
                   cite("capacity", "900 ml")],
        image_urls=["https://www.anex.pk/1.jpg"] * 3,
    )


async def _run_with_writer_failure() -> dict:
    """Runs the real graph with the writer's LLM call raising."""
    scraped = {"scraped_data": [{
        "url": "https://www.anex.pk/ag-01", "source_type": "official",
        "content": SOURCE_TEXT, "candidate_titles": ["Anex AG-01 Handy Pull Chopper"],
    }]}

    async def llm(role, system_prompt, human_prompt, response_model):
        if response_model is WriterOutput:
            raise RuntimeError("groq: rate limit exceeded")
        return _extraction()

    with (
        patch("app.graph.nodes.brands_repo.get_by_name_ci", AsyncMock(return_value=BRAND)),
        patch("app.graph.nodes.brands_repo.get_by_name", AsyncMock(return_value=BRAND)),
        patch("app.graph.nodes.categories_repo.get_by_name", AsyncMock(return_value=CATEGORY)),
        patch("app.graph.nodes.categories_repo.get", AsyncMock(return_value=PARENT)),
        patch("app.graph.nodes.taxonomy_repo.get_schema_by_category", AsyncMock(return_value=SCHEMA)),
        patch("app.graph.nodes.settings_repo.get_setting", AsyncMock(return_value="augment")),
        patch("app.graph.nodes.scrape_product", AsyncMock(return_value=scraped)),
        patch("app.graph.nodes._build_operator_source_docs", AsyncMock(return_value=[])),
        patch("app.graph.nodes.llm_provider.call", llm),
        patch("app.graph.nodes.manual_review_repo.add", AsyncMock()) as review_add,
        patch("app.graph.nodes.google_search_client") as gs,
    ):
        gs.configured = False
        final = await pipeline.ainvoke(
            PipelineState(product_id=uuid4(), batch_id=uuid4(), raw_input=_raw())
        )
    return {"state": final, "review_add": review_add}


@pytest.mark.asyncio
async def test_a_writer_failure_does_not_crash_the_pipeline():
    """
    THE BUG. A writer LLM failure is ordinary -- a rate limit, a timeout, a
    malformed response. It must escalate one product, not raise out of
    pipeline.ainvoke().
    """
    result = await _run_with_writer_failure()   # must not raise
    state = result["state"]
    state = state if isinstance(state, dict) else state.model_dump()

    assert state.get("manual_review_required") is True


@pytest.mark.asyncio
async def test_the_writers_own_failure_reason_survives():
    """
    The point of escalating rather than crashing: the operator needs the cause.
    "groq: rate limit exceeded" is actionable; an AttributeError on hero_heading
    is not.
    """
    state = (await _run_with_writer_failure())["state"]
    state = state if isinstance(state, dict) else state.model_dump()

    failure = state.get("failure")
    detail = getattr(failure, "detail", None) or (failure or {}).get("detail", "")
    assert "Writer LLM call failed" in detail, f"the writer's reason was replaced: {detail!r}"
    assert "rate limit" in detail
    assert "hero_heading" not in detail, "reviewer_node ran on a None writer_output"


@pytest.mark.asyncio
async def test_the_product_reaches_the_manual_review_queue():
    """escalation_handler is the only thing that files it; it must actually run."""
    result = await _run_with_writer_failure()
    result["review_add"].assert_awaited_once()


def test_no_failing_node_has_an_unconditional_outgoing_edge():
    """
    THE LOCK. Walks the compiled graph and pairs it against the source: any node
    that can return manual_review_required=True must route through a conditional
    edge, or its failure is silently overwritten by whatever runs next.

    Derived from the AST rather than a hand-written list, so a node added later
    is covered automatically.
    """
    import ast
    import pathlib

    nodes_src = pathlib.Path(__file__).resolve().parents[2] / "app" / "graph" / "nodes.py"
    tree = ast.parse(nodes_src.read_text(encoding="utf-8"))

    can_fail: set[str] = set()
    for fn in tree.body:
        if not isinstance(fn, ast.AsyncFunctionDef | ast.FunctionDef):
            continue
        for n in ast.walk(fn):
            if not (isinstance(n, ast.Return) and isinstance(n.value, ast.Dict)):
                continue
            for key, value in zip(n.value.keys, n.value.values, strict=False):
                if (isinstance(key, ast.Constant) and key.value == "manual_review_required"
                        and isinstance(value, ast.Constant) and value.value is True):
                    can_fail.add(fn.name)

    assert "writer_node" in can_fail, "AST scan broke -- it should find writer_node"

    graph = pipeline.get_graph()
    # A conditional edge carries a branch label; an unconditional one does not.
    unconditional: dict[str, list[str]] = {}
    for edge in graph.edges:
        if getattr(edge, "conditional", False) or getattr(edge, "data", None):
            continue
        unconditional.setdefault(edge.source, []).append(edge.target)

    offenders = {
        node: targets for node, targets in unconditional.items()
        if node in can_fail and targets != ["__end__"]
    }
    assert not offenders, (
        f"these nodes can fail but their failure is ignored by an unconditional "
        f"edge, so the next node runs on a half-built state: {offenders}"
    )


def _writer_output() -> WriterOutput:
    """A structurally valid WriterOutput -- content quality is not the point here."""
    return WriterOutput(
        hero_heading="Anex AG-01 Handy Pull Chopper",
        hero_paragraph="The Anex AG-01 Handy Pull Chopper chops with a pull cord. " * 3,
        feature_headings=["Pull Cord", "900 ml Bowl", "Three Blades"],
        feature_texts=["Anex AG-01 pull cord operation.", "900 ml bowl capacity.",
                       "Three stainless steel blades."],
        features_bullets=["900 ml bowl", "3 blades", "Pull cord", "No power needed"],
        faqs=[FAQPair(question=f"Q{i}?", answer=f"A{i}") for i in range(4)]
        + [FAQPair(question="What is the official warranty?", answer="2 Years Warranty")],
        short_desc_feature_1="900 ml bowl",
        short_desc_feature_2="3 stainless steel blades",
        short_desc_feature_3="Pull cord operation",
        rank_math_description="Anex AG-01 Handy Pull Chopper with a 900 ml bowl and "
                              "three blades, 2 Years Warranty. Order now at Kia Chahiye.",
        lsi_keywords=["AG-01 chopper", "Anex hand chopper", "900 ml chopper bowl"],
        alt_text_1="Anex AG-01", alt_text_2="Anex AG-01", alt_text_3="Anex AG-01",
    )


@pytest.mark.asyncio
async def test_a_failure_on_a_writer_RETRY_does_not_ship_the_previous_attempt():
    """
    The case the first three tests miss, found by mutation testing: on a retry
    the state still holds the PREVIOUS attempt's writer_output, because a node
    returning a failure dict does not clear the fields an earlier pass set.

    So "does writer_output exist" is not enough to detect the failure. The
    outcome is still safe without the extra check -- after_review_router has its
    own state.failure guard -- but the reviewer would be called AGAIN on stale
    content from a run that errored. At 300 products that is a wasted LLM call
    and its latency on every doomed retry, so the assertion below is on the
    reviewer NOT being re-entered, which is what the check actually buys.
    """
    scraped = {"scraped_data": [{
        "url": "https://www.anex.pk/ag-01", "source_type": "official",
        "content": SOURCE_TEXT, "candidate_titles": ["Anex AG-01 Handy Pull Chopper"],
    }]}
    writer_calls = {"n": 0}

    async def llm(role, system_prompt, human_prompt, response_model):
        if response_model is WriterOutput:
            writer_calls["n"] += 1
            if writer_calls["n"] == 1:
                return _writer_output()          # attempt 1 succeeds
            raise RuntimeError("groq: rate limit exceeded")   # attempt 2 dies
        return _extraction()

    # Reviewer rejects attempt 1, sending the graph back to the writer.
    review_calls = {"n": 0}

    async def failing_review(state):
        review_calls["n"] += 1
        return {"review_result": ReviewResult(
            passed=False, preflight_score=40, checks=[],
            warranty_consistent=True, fact_cross_check_passed=True,
            fact_cross_check_notes=[], failure_summary="keyword density too low",
        )}

    with (
        patch("app.graph.nodes.brands_repo.get_by_name_ci", AsyncMock(return_value=BRAND)),
        patch("app.graph.nodes.brands_repo.get_by_name", AsyncMock(return_value=BRAND)),
        patch("app.graph.nodes.categories_repo.get_by_name", AsyncMock(return_value=CATEGORY)),
        patch("app.graph.nodes.categories_repo.get", AsyncMock(return_value=PARENT)),
        patch("app.graph.nodes.taxonomy_repo.get_schema_by_category", AsyncMock(return_value=SCHEMA)),
        patch("app.graph.nodes.settings_repo.get_setting", AsyncMock(return_value="augment")),
        patch("app.graph.nodes.scrape_product", AsyncMock(return_value=scraped)),
        patch("app.graph.nodes._build_operator_source_docs", AsyncMock(return_value=[])),
        patch("app.graph.nodes.llm_provider.call", llm),
        patch("app.graph.nodes.manual_review_repo.add", AsyncMock()),
        patch("app.graph.pipeline.reviewer_node", failing_review),
        patch("app.graph.nodes.google_search_client") as gs,
    ):
        gs.configured = False
        from app.graph.pipeline import create_pipeline
        graph = create_pipeline()
        final = await graph.ainvoke(
            PipelineState(product_id=uuid4(), batch_id=uuid4(), raw_input=_raw())
        )

    final = final if isinstance(final, dict) else final.model_dump()
    assert writer_calls["n"] >= 2, "the retry loop did not run; this test proves nothing"
    assert final.get("manual_review_required") is True, (
        "a product whose writer errored on retry was allowed through on the "
        "previous attempt's content"
    )
    assert not final.get("csv_row"), "stale content reached the CSV row"
    assert review_calls["n"] == 1, (
        f"the reviewer ran {review_calls['n']} times -- it was re-entered on the "
        f"failed attempt's stale writer_output instead of escalating"
    )


@pytest.mark.asyncio
async def test_a_colliding_sku_never_gets_a_csv_row_built():
    """
    The second unconditional edge. A SKU already present in the WooCommerce
    snapshot is doomed -- importing it OVERWRITES a live product instead of
    creating one. duplicate_sku_guard_node returns that failure correctly, but
    the plain edge ran csv_row_assembler_node anyway, so a row was assembled and
    persisted for a product that must never be exported.

    Contained before the fix (manual_review_required maps to
    status="manual_review", so bulk_run's `ready` filter excluded it) -- but a
    stored csv_row on a rejected product is one filter change away from
    shipping.
    """
    scraped = {"scraped_data": [{
        "url": "https://www.anex.pk/ag-01", "source_type": "official",
        "content": SOURCE_TEXT, "candidate_titles": ["Anex AG-01 Handy Pull Chopper"],
    }]}

    async def llm(role, system_prompt, human_prompt, response_model):
        if response_model is WriterOutput:
            return _writer_output()
        return _extraction()

    async def passing_review(state):
        return {"review_result": ReviewResult(
            passed=True, preflight_score=95, checks=[],
            warranty_consistent=True, fact_cross_check_passed=True,
            fact_cross_check_notes=[],
        )}

    assembler_calls = {"n": 0}
    from app.graph.nodes import csv_row_assembler_node as real_assembler

    async def counting_assembler(state):
        assembler_calls["n"] += 1
        return await real_assembler(state)

    with (
        patch("app.graph.nodes.brands_repo.get_by_name_ci", AsyncMock(return_value=BRAND)),
        patch("app.graph.nodes.brands_repo.get_by_name", AsyncMock(return_value=BRAND)),
        patch("app.graph.nodes.categories_repo.get_by_name", AsyncMock(return_value=CATEGORY)),
        patch("app.graph.nodes.categories_repo.get", AsyncMock(return_value=PARENT)),
        patch("app.graph.nodes.taxonomy_repo.get_schema_by_category", AsyncMock(return_value=SCHEMA)),
        patch("app.graph.nodes.settings_repo.get_setting", AsyncMock(return_value="augment")),
        patch("app.graph.nodes.scrape_product", AsyncMock(return_value=scraped)),
        patch("app.graph.nodes._build_operator_source_docs", AsyncMock(return_value=[])),
        patch("app.graph.nodes.llm_provider.call", llm),
        patch("app.graph.nodes.manual_review_repo.add", AsyncMock()),
        patch("app.graph.nodes.check_sku_collision", AsyncMock(return_value=True)),
        patch("app.graph.nodes.sources_repo.get_brand_aliases", AsyncMock(return_value=[])),
        patch("app.graph.pipeline.reviewer_node", passing_review),
        patch("app.graph.pipeline.csv_row_assembler_node", counting_assembler),
        patch("app.graph.nodes.google_search_client") as gs,
    ):
        gs.configured = False
        from app.graph.pipeline import create_pipeline
        final = await create_pipeline().ainvoke(
            PipelineState(product_id=uuid4(), batch_id=uuid4(), raw_input=_raw())
        )

    final = final if isinstance(final, dict) else final.model_dump()
    assert final.get("manual_review_required") is True
    assert assembler_calls["n"] == 0, (
        "the CSV row assembler ran for a product with a colliding SKU"
    )
    assert not final.get("csv_row"), "a csv_row was built for a colliding SKU"
