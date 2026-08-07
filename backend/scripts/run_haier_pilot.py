"""
Live pilot run for ONE real Haier refrigerator from the owner's sheet.

Runs the exact production path -- real source discovery against haier.com/pk,
real Gemini/Groq extraction, deterministic builders, the 49-column CSV -- and
prints whatever ACTUALLY happens. If the specs verify, a CSV row is written; if
they cannot be verified, the product escalates to Manual Review with a reason.
Both outcomes are the backend working; neither is faked.
"""
import asyncio
import csv
import io
import json
from decimal import Decimal

from app.builders.csv_assembler import COLUMN_ORDER
from app.db.repositories.batches import batches_repo
from app.db.repositories.products import products_repo
from app.graph.batch_processor import BatchProcessor
from app.models.raw_input import RawProductInput


async def main():
    batch_id = await batches_repo.create_batch("Haier Pilot — HRF-246 IPGA")
    print(f"batch: {batch_id}")

    raw_input = RawProductInput(
        # SKU = model + colour, exactly as the input adapter would build it.
        sku="HRF-246-IPGA-GREEN",
        model_number="HRF-246 IPGA",
        brand_name="HAIER",            # exact live-taxonomy casing
        category_name="Refrigerator",  # exact live-taxonomy casing
        product_type="Refrigerator",
        regular_price=Decimal(90000),
        sale_price=Decimal(74999),
        in_stock=True,
        template_choice="A",  # sheet says "Description complete" + images found
        warranty_override=(
            "10 Year Warranty on Compressor (Including Gas); "
            "3 Year Warranty on Electronics; 1 Year Warranty on Other Parts"
        ),
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
    print(f"product: {product.id}\nrunning full pipeline (real scraping + LLM)...\n")

    await BatchProcessor.run_batch(batch_id)

    final = await products_repo.get(product.id)
    print("=" * 70)
    print(f"STATUS: {final.status}")
    if final.status != "ready_for_qa":
        print(f"failure_reason: {final.failure_reason}")
        print(f"failure_detail: {final.failure_detail}")
        print("\n-> Escalated. No CSV row written (this is the safety path, not a crash).")
        return

    print(f"NAME:  {final.name}")
    print(f"TITLE: {final.rank_math_title}")
    print(f"FOCUS: {final.rank_math_focus_keyword}")
    print(f"META:  {final.rank_math_description}")

    # Show the real assembled CSV row if one was persisted.
    row = getattr(final, "csv_row", None)
    if row:
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=COLUMN_ORDER, quoting=csv.QUOTE_ALL)
        writer.writeheader()
        writer.writerow({k: row.get(k, "") for k in COLUMN_ORDER})
        out = "scripts/_haier_pilot_output.csv"
        with open(out, "w", newline="", encoding="utf-8") as f:
            f.write(buf.getvalue())
        print(f"\nCSV written: {out}  ({len(COLUMN_ORDER)} columns)")


if __name__ == "__main__":
    asyncio.run(main())
