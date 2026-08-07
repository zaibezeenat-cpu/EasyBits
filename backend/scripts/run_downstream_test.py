"""
Phase 3 verification, part 2: proves the Writer -> Reviewer -> deterministic
builders -> CSV assembler chain works end-to-end with real LLM calls and a
real Supabase write, decoupled from whether a specific test SKU happens to
have full data on the two trusted secondary sources today (run_integration_test.py
already proved that path correctly escalates instead of guessing, which is
correct behavior, not a failure).

The ExtractionResult below is a hand-built stand-in for what extractor_node
would have produced from real scraped text -- not a claim about a real
product, purely a fixture to exercise the real downstream code.
"""
import asyncio
import json
from datetime import UTC, datetime
from decimal import Decimal

from app.db.repositories.batches import batches_repo
from app.db.repositories.categories import categories_repo
from app.db.repositories.products import products_repo
from app.db.repositories.taxonomy import taxonomy_repo
from app.graph.batch_processor import _final_state_to_product_update
from app.graph.nodes import (
    csv_row_assembler_node,
    deterministic_builders_node,
    duplicate_sku_guard_node,
    html_sanitize_node,
    image_fallback_node,
    reviewer_node,
    writer_node,
)
from app.graph.state import PipelineState
from app.models.extraction import ExtractionResult, SourceCitation
from app.models.raw_input import RawProductInput


async def main():
    category = await categories_repo.get_by_name("Microwave Oven")
    schema = await taxonomy_repo.get_schema_by_category(category.id)

    batch_id = await batches_repo.create_batch("Downstream Test Batch")
    raw_input = RawProductInput(
        sku="TEST-DOWNSTREAM-01",
        model_number="DW-131 HP Sync",
        brand_name="DAWLANCE",
        category_name="Microwave Oven",
        product_type="Microwave Oven",
        regular_price=Decimal(29000),
        sale_price=Decimal(27500),
        in_stock=True,
        template_choice="A",
        warranty_override="1 Year Official Warranty",
    )
    product = await products_repo.create({
        "batch_id": str(batch_id),
        "sku": raw_input.sku,
        "model_number": raw_input.model_number,
        "raw_input": json.loads(raw_input.model_dump_json()),
        "regular_price": float(raw_input.regular_price),
        "sale_price": float(raw_input.sale_price) if raw_input.sale_price is not None else None,
        "in_stock": raw_input.in_stock,
    })

    now = datetime.now(UTC)
    fixture_extraction = ExtractionResult(
        product_id=str(product.id),
        category_key="microwave_oven",
        citations=[
            SourceCitation(field_name="brand", value="DAWLANCE", source_url="https://example-fixture.test/p", source_type="official", confidence="confirmed", fetched_at=now),
            SourceCitation(field_name="model_number", value="DW-131 HP Sync", source_url="https://example-fixture.test/p", source_type="official", confidence="confirmed", fetched_at=now),
            SourceCitation(field_name="appliance_type", value="Grill Microwave Oven", source_url="https://example-fixture.test/p", source_type="official", confidence="confirmed", fetched_at=now),
            SourceCitation(field_name="capacity", value="30 Liters", source_url="https://example-fixture.test/p", source_type="official", confidence="confirmed", fetched_at=now),
            SourceCitation(field_name="control_panel", value="Digital Touch Control", source_url="https://example-fixture.test/p", source_type="official", confidence="confirmed", fetched_at=now),
            SourceCitation(field_name="features", value="UNKNOWN", source_url=None, source_type="official", confidence="unreachable", fetched_at=now),
            SourceCitation(field_name="weight_kg", value="UNKNOWN", source_url=None, source_type="official", confidence="unreachable", fetched_at=now),
            SourceCitation(field_name="length_cm", value="UNKNOWN", source_url=None, source_type="official", confidence="unreachable", fetched_at=now),
            SourceCitation(field_name="width_cm", value="UNKNOWN", source_url=None, source_type="official", confidence="unreachable", fetched_at=now),
            SourceCitation(field_name="height_cm", value="UNKNOWN", source_url=None, source_type="official", confidence="unreachable", fetched_at=now),
        ],
        image_urls=[],
        scraped_official_price=None,
    )

    state = PipelineState(
        product_id=product.id,
        batch_id=batch_id,
        raw_input=raw_input,
        category_schema=schema,
        extraction=fixture_extraction,
    )

    print("Running: image_fallback_node")
    state = state.model_copy(update=await image_fallback_node(state))
    print(f"  selected_template_type = {state.selected_template_type}")

    print("Running: writer_node (real LLM call)")
    update = await writer_node(state)
    state = state.model_copy(update=update)
    if state.failure:
        print(f"  FAILED: {state.failure}")
        return
    print(f"  name = {state.name}")
    print(f"  rank_math_title = {state.rank_math_title}")

    print("Running: reviewer_node (real LLM call)")
    update = await reviewer_node(state)
    state = state.model_copy(update=update)
    if state.failure:
        print(f"  FAILED: {state.failure}")
    print(f"  review passed = {state.review_result.passed if state.review_result else None}")
    if state.review_result and not state.review_result.passed:
        print(f"  failure_summary = {state.review_result.failure_summary}")
        for c in state.review_result.checks:
            if not c.passed:
                print(f"    FAILED CHECK: {c.check_name} -> {c.detail}")

    print("Running: deterministic_builders_node")
    state = state.model_copy(update=await deterministic_builders_node(state))

    print("Running: html_sanitize_node")
    state = state.model_copy(update=await html_sanitize_node(state))

    print("Running: duplicate_sku_guard_node")
    update = await duplicate_sku_guard_node(state)
    state = state.model_copy(update=update)
    if state.failure:
        print(f"  FAILED: {state.failure}")
        return

    print("Running: csv_row_assembler_node")
    update = await csv_row_assembler_node(state)
    state = state.model_copy(update=update)
    if state.failure:
        print(f"  FAILED: {state.failure}")
        return

    print("\n=== CSV ROW PRODUCED ===")
    print(f"columns: {len(state.csv_row)}")
    for k, v in state.csv_row.items():
        s = str(v)
        print(f"  {k}: {s[:150]}")

    persist_update = _final_state_to_product_update(state)
    await products_repo.update_product(product.id, persist_update)
    final = await products_repo.get(product.id)
    print(f"\nPersisted product status: {final.status}")
    print(f"Persisted csv_row column count: {len(final.csv_row)}")


if __name__ == "__main__":
    asyncio.run(main())
