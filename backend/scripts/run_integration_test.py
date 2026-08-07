"""
One-off manual integration test (Phase 3): create a real batch + product row,
then run it through the real BatchProcessor.run_batch() path against the real
Supabase DB and real Gemini/Groq LLM calls. Not a permanent test -- exercises
the exact code path a real batch submission would use, including the
persistence fix in batch_processor.py.
"""
import asyncio
import json
from decimal import Decimal

from app.db.repositories.batches import batches_repo
from app.db.repositories.products import products_repo
from app.graph.batch_processor import BatchProcessor
from app.models.raw_input import RawProductInput


async def main():
    batch_id = await batches_repo.create_batch("Integration Test Batch")
    print(f"Created batch: {batch_id}")

    raw_input = RawProductInput(
        sku="TEST-DW131HP-INTEGRATION",
        model_number="DW-131 HP Sync",
        brand_name="DAWLANCE",
        category_name="Microwave Oven",
        product_type="Microwave Oven",
        regular_price=Decimal(29000),
        sale_price=Decimal(27500),
        in_stock=True,
        template_choice="A",
        # TEST-ONLY value. warranty_matrix has no real seeded data yet (that
        # requires the user's real business data), so this exercises the
        # warranty_override path deliberately rather than letting the pipeline
        # fabricate anything -- do not treat this as real warranty data.
        warranty_override="1 Year Official Warranty",
    )

    product = await products_repo.create({
        "batch_id": str(batch_id),
        "sku": raw_input.sku,
        "model_number": raw_input.model_number,
        "raw_input": json.loads(raw_input.model_dump_json()),
        "regular_price": float(raw_input.regular_price),
        "sale_price": float(raw_input.sale_price),
        "in_stock": raw_input.in_stock,
    })
    print(f"Created product: {product.id}")

    print("Running batch...")
    await BatchProcessor.run_batch(batch_id)

    final = await products_repo.get(product.id)
    print("\n=== FINAL PRODUCT STATE ===")
    print(f"status: {final.status}")
    print(f"failure_reason: {final.failure_reason}")
    print(f"failure_detail: {final.failure_detail}")
    print(f"name: {final.name}")
    print(f"rank_math_title: {final.rank_math_title}")
    print(f"rank_math_focus_keyword: {final.rank_math_focus_keyword}")
    print(f"rank_math_description: {final.rank_math_description}")
    print(f"preflight_score: {final.preflight_score}")
    print(f"retry_count: {final.retry_count}")
    print(f"csv_row keys: {list(final.csv_row.keys()) if final.csv_row else None}")
    print(f"review_result: {json.dumps(final.review_result, indent=2)[:2000] if final.review_result else None}")


if __name__ == "__main__":
    asyncio.run(main())
