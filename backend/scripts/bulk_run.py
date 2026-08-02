"""
Bulk CSV generator — CLI.

Reads a sheet of products, runs each through the full pipeline (scrape/operator
source -> extract -> corroborate -> write -> SEO -> 51-col CSV), and writes the
WooCommerce import CSV for the products that came out READY. Products the system
was not confident about are listed in a separate review report -- never guessed.

Usage (from backend/):
    python scripts/bulk_run.py input.csv output.csv
    python scripts/bulk_run.py input.csv output.csv --strict   # use only provided
                                                                # link/details, no discovery

INPUT CSV headers (case-insensitive; only Name + one price are required):
    Name        (or "Product", "Raw Product Data", "Model")
    Regular     (or "Regular Price")
    Sale        (or "Sale Price")
    Warranty
    Status      ("images FOUND" -> Template A, else Template B)
    Website Link (or "Link", "URL")
    Details
    Existing ID  (fills the CSV ID column -> WooCommerce UPDATE instead of create)
"""
import argparse
import asyncio
import csv
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.builders.category_classifier import llm_pick_category  # noqa: E402
from app.builders.csv_assembler import generate_csv_file  # noqa: E402
from app.builders.input_adapter import parse_sheet_row  # noqa: E402
from app.api.routes.products import build_product_row  # noqa: E402
from app.db.repositories.batches import batches_repo  # noqa: E402
from app.db.repositories.brands import brands_repo  # noqa: E402
from app.db.repositories.categories import categories_repo  # noqa: E402
from app.db.repositories.products import products_repo  # noqa: E402
from app.db.repositories.settings import settings_repo  # noqa: E402
from app.graph.batch_processor import BatchProcessor  # noqa: E402
from app.models.raw_input import RawProductInput  # noqa: E402


def _pick(row: dict, *names: str) -> str:
    """First non-empty value among the given header names (case-insensitive)."""
    lower = {k.strip().lower(): (v or "").strip() for k, v in row.items() if k}
    for n in names:
        v = lower.get(n.lower())
        if v:
            return v
    return ""


def _to_decimal(value: str):
    digits = "".join(c for c in (value or "") if c.isdigit() or c == ".")
    try:
        return Decimal(digits) if digits else None
    except InvalidOperation:
        return None


async def _build_inputs(rows: list[dict]) -> tuple[list[RawProductInput], list[str]]:
    known_brands = await brands_repo.get_active_names()
    known_categories, category_parents = await categories_repo.get_active_names_and_parents()

    inputs: list[RawProductInput] = []
    skipped: list[str] = []

    for i, row in enumerate(rows, 1):
        name = _pick(row, "Name", "Product", "Raw Product Data", "Model")
        reg = _to_decimal(_pick(row, "Regular", "Regular Price"))
        sale = _to_decimal(_pick(row, "Sale", "Sale Price"))
        if not name or reg is None or sale is None:
            skipped.append(f"row {i}: missing name or a price ({name!r})")
            continue

        parsed = parse_sheet_row(
            product_name=name, price_a=reg, price_b=sale,
            warranty_text=_pick(row, "Warranty"),
            status_text=_pick(row, "Status"),
            known_brands=known_brands, known_categories=known_categories,
            category_parents=category_parents,
        )

        # Brand: prefer an explicit "Brand" column (matched to the exact taxonomy
        # casing), else the brand inferred from the product name.
        brand_name = parsed.brand_name
        brand_col = _pick(row, "Brand")
        if brand_col:
            brand_name = next((b for b in known_brands if b.lower() == brand_col.lower()), None)
            if brand_name is None:
                skipped.append(f"row {i}: brand '{brand_col}' not in taxonomy for {name!r}")
                continue

        category = parsed.category_name
        if category is None:  # deterministic match failed -> LLM picks from the list
            category = await llm_pick_category(name, known_categories)

        if not brand_name or not category or not parsed.sku:
            missing = []
            if not brand_name:
                missing.append("brand")
            if not category:
                missing.append("category")
            if not parsed.sku:
                missing.append("sku/model")
            skipped.append(f"row {i}: could not resolve {', '.join(missing)} for {name!r}")
            continue

        existing_id = _pick(row, "Existing ID", "Existing Id", "ID")
        inputs.append(RawProductInput(
            sku=parsed.sku, model_number=parsed.model_number,
            brand_name=brand_name, category_name=category,
            product_type=category,  # extraction refines the real type for the title
            regular_price=parsed.regular_price, sale_price=parsed.sale_price,
            warranty_override=parsed.warranty_phrase,
            template_choice=parsed.template_choice or "B",
            official_url=_pick(row, "Website Link", "Link", "URL") or None,
            source_details=_pick(row, "Details") or None,
            existing_id=existing_id or None,
        ))

    return inputs, skipped


async def run(input_path: str, output_path: str, strict: bool) -> None:
    rows = list(csv.DictReader(open(input_path, encoding="utf-8-sig")))
    print(f"Read {len(rows)} rows from {input_path}")

    inputs, skipped = await _build_inputs(rows)
    print(f"Resolved {len(inputs)} products; {len(skipped)} could not be resolved.")
    for s in skipped:
        print("  SKIP", s)
    if not inputs:
        print("Nothing to process.")
        return

    prev_mode = await settings_repo.get_setting("provided_source_mode")
    if strict:
        await settings_repo.update_setting("provided_source_mode", "strict")
    try:
        batch_id = await batches_repo.create_batch(f"Bulk import ({len(inputs)} products)")
        await products_repo.create_many([build_product_row(batch_id, r) for r in inputs])
        print(f"Batch {batch_id} created. Running pipeline (this can take a while)...")
        await BatchProcessor.run_batch(batch_id)
    finally:
        if strict:
            await settings_repo.update_setting("provided_source_mode", prev_mode or "augment")

    products = await products_repo.get_by_batch(batch_id)
    ready = [p for p in products if p.status == "ready_for_qa" and p.csv_row]
    review = [p for p in products if p.status != "ready_for_qa"]

    with open(output_path, "w", encoding="utf-8-sig", newline="") as f:
        f.write(generate_csv_file([p.csv_row for p in ready]))

    print(f"\n===== DONE =====")
    print(f"READY  -> {len(ready)} products written to {output_path}")
    print(f"REVIEW -> {len(review)} products need attention:")
    for p in review:
        reason = p.failure_reason or "see review queue"
        detail = ""
        if isinstance(p.failure_detail, dict):
            detail = str(p.failure_detail.get("detail", ""))[:120]
        print(f"  {p.sku}: {reason} {detail}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Bulk-generate the kiachahiye 51-column WooCommerce CSV.")
    ap.add_argument("input", help="input products CSV")
    ap.add_argument("output", help="output WooCommerce CSV")
    ap.add_argument("--strict", action="store_true",
                    help="use only the provided link/details (no discovery); fastest")
    args = ap.parse_args()
    asyncio.run(run(args.input, args.output, args.strict))


if __name__ == "__main__":
    main()
