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

from app.api.routes.products import build_product_row
from app.builders.category_classifier import llm_pick_category
from app.builders.csv_assembler import generate_csv_file
from app.builders.input_adapter import parse_sheet_row
from app.db.repositories.batches import batches_repo
from app.db.repositories.brands import brands_repo
from app.db.repositories.categories import categories_repo
from app.db.repositories.products import products_repo
from app.db.repositories.settings import settings_repo
from app.graph.batch_processor import BatchProcessor
from app.models.raw_input import RawProductInput


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


# The operator's marketing anchor: a single-price row still shows a discount,
# 20% either side of the one price given.
MARKUP = Decimal("1.20")


def _resolve_prices(reg: Decimal | None, sale: Decimal | None) -> tuple[Decimal, Decimal | None] | None:
    """
    Resolves the sheet's "Regular"/"Sale" columns into (regular_price, sale_price).

    Unlike input_adapter.assign_prices (used by the UI paste-flow, which never
    sees a column header and so has no choice but to derive roles from the
    values), this CSV path reads named columns -- the operator's label is
    authoritative here. Two explicit business rules, both confirmed by the
    operator (kiachahiye.pk), not system defaults:

    1. HEADERS ARE TRUSTED. A sheet claiming Sale > Regular is a mistake in the
       sheet, not a swap to perform silently -- raises ValueError so the row is
       skipped with a clear reason instead of shipping a wrong price.
    2. A SINGLE PRICE GETS A 20% MARKUP ANCHOR, in whichever direction the
       missing price falls, so the storefront always shows a discount. This is
       deliberate marketing policy the operator asked for -- it reverses an
       earlier fix in this file that removed the same markup as a fabricated
       price; the difference is that this is now their stated business rule,
       not a code default nobody chose.

    Args:
        reg: The sheet's "Regular" column, or None if blank.
        sale: The sheet's "Sale" column, or None if blank.

    Returns:
        (regular_price, sale_price) with sale_price None when there is no
        discount, or None when neither price was given (caller skips the row).

    Raises:
        ValueError: if both are given and sale > reg.
    """
    if reg is None and sale is None:
        return None
    if reg is not None and sale is not None:
        if sale > reg:
            raise ValueError(
                f"Sale price {sale} is higher than Regular price {reg} -- "
                f"fix the sheet (the Sale column should be the LOWER price)"
            )
        if sale == reg:
            return reg, None
        return reg, sale
    if sale is not None:  # only "Sale" given -> Regular is the 20%-above anchor
        return (sale * MARKUP).quantize(Decimal(1)), sale
    # only "Regular" given -> Sale is the 20%-below discount
    return reg, (reg / MARKUP).quantize(Decimal(1))


async def _build_inputs(rows: list[dict]) -> tuple[list[RawProductInput], list[str]]:
    known_brands = await brands_repo.get_active_names()
    known_categories, category_parents = await categories_repo.get_active_names_and_parents()

    inputs: list[RawProductInput] = []
    skipped: list[str] = []

    for i, row in enumerate(rows, 1):
        name = _pick(row, "Name", "Product", "Raw Product Data", "Model", "Title", "post_title", "Official_Model_Title")
        reg_str = _pick(row, "Regular", "Regular Price", "Regular price", "Price", "Original_PRICE")
        sale_str = _pick(row, "Sale", "Sale Price", "Sale price", "Sale_Price")
        
        try:
            resolved = _resolve_prices(_to_decimal(reg_str), _to_decimal(sale_str))
        except ValueError as e:
            skipped.append(f"row {i}: {e} ({name!r})")
            continue

        if not name or resolved is None:
            skipped.append(f"row {i}: missing name or a price ({name!r})")
            continue
        reg, sale = resolved

        # price_a/price_b feed input_adapter.assign_prices, which re-derives
        # regular-vs-sale from the two VALUES (it is also used by the UI
        # paste-flow, which never sees a header). reg is already the larger of
        # the two by construction above, so this is a no-op here -- it never
        # sees a case it would resolve differently.
        parsed = parse_sheet_row(
            product_name=name, price_a=reg, price_b=(sale if sale is not None else reg),
            warranty_text=_pick(row, "Warranty", "Warranty Details"),
            status_text=_pick(row, "Status", "Template", "Template Choice"),
            known_brands=known_brands, known_categories=known_categories,
            category_parents=category_parents,
        )

        # Brand: prefer an explicit "Brand" column (matched to the exact taxonomy
        # casing), else the brand inferred from the product name.
        brand_name = parsed.brand_name
        brand_col = _pick(row, "Brand", "Vendor", "Brand Name", "pa_brand")
        if brand_col:
            brand_name = next((b for b in known_brands if b.lower() == brand_col.lower()), None)
            if brand_name is None:
                skipped.append(f"row {i}: brand '{brand_col}' not in taxonomy for {name!r}")
                continue

        # Category: prefer an explicit "Category" column, same contract as the
        # Brand override above. A bare product name genuinely cannot say "Manual
        # Chopper" vs "Chopper" when the word "manual" is never in it (e.g. Anex's
        # own title "Handy Pull Chopper") -- no pattern match, embedding, or LLM
        # guess can recover information that was never in the text, and letting an
        # LLM guess from a SKU/model number alone would be exactly the kind of
        # unverifiable inference the rest of this pipeline refuses to publish. The
        # operator can see the real product, so they state it directly instead.
        category = parsed.category_name
        category_col = _pick(row, "Category", "Product Category", "pa_category")
        if category_col:
            category = next((c for c in known_categories if c.lower() == category_col.lower()), None)
            if category is None:
                skipped.append(f"row {i}: category '{category_col}' not in taxonomy for {name!r}")
                continue
        elif category is None:  # deterministic match failed -> LLM picks from the list
            category = await llm_pick_category(name, known_categories)

        explicit_sku = _pick(row, "SKU")
        if explicit_sku:
            parsed.sku = explicit_sku
            if not parsed.model_number:
                parsed.model_number = explicit_sku

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

        existing_id = _pick(row, "Existing ID", "Existing Id", "ID", "id")
        inputs.append(RawProductInput(
            sku=parsed.sku, model_number=parsed.model_number,
            brand_name=brand_name, category_name=category,
            product_type=category,  # extraction refines the real type for the title
            regular_price=parsed.regular_price, sale_price=parsed.sale_price,
            warranty_override=parsed.warranty_phrase,
            template_choice=parsed.template_choice or "B",
            official_url=_pick(row, "Website Link", "Link", "URL", "Product_URL", "External URL") or None,
            source_details=_pick(row, "Details", "Description", "Short description", "Clean_Description_Text", "Original_Item Description") or None,
            existing_id=existing_id or None,
            passthrough_columns=dict(row),  # Capture entire row for passthrough overlay
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

    print("\n===== DONE =====")
    print(f"READY  -> {len(ready)} products written to {output_path}")
    print(f"REVIEW -> {len(review)} products need attention:")
    for p in review:
        reason = p.failure_reason or "see review queue"
        detail = ""
        if isinstance(p.failure_detail, dict):
            detail = str(p.failure_detail.get("detail", ""))[:120]
        print(f"  {p.sku}: {reason} {detail}")

    _print_inferred_report(ready)


def _print_inferred_report(products: list) -> None:
    """Lists every value that was DEDUCED rather than read from a source.

    This is the operator's review surface. Inferred values ship in the CSV
    unmarked -- a "(based on features)" suffix on a live storefront reads badly to
    customers -- so without this report a deduction would be invisible. There is
    no usable admin UI, which makes the terminal the only place a human sees them
    before the CSV is uploaded.

    Each line carries the quote the deduction rests on, so it can be judged
    without opening the source page.

    Args:
        products: The products that reached READY, i.e. the ones whose values are
            about to be imported.
    """
    lines: list[tuple[str, str, str, str]] = []
    for p in products:
        extraction = p.extraction_result or {}
        for citation in extraction.get("citations", []):
            if citation.get("confidence") != "inferred":
                continue
            lines.append((
                p.sku,
                citation.get("field_name", "?"),
                citation.get("value", "?"),
                (citation.get("exact_quote") or "").strip(),
            ))

    if not lines:
        return

    skus = {sku for sku, *_ in lines}
    print(
        f"\nINFERRED VALUES ({len(skus)} product(s), {len(lines)} value(s)) "
        f"— deduced from described features, not stated by any source:"
    )
    for sku, field, value, quote in lines:
        print(f"  {sku:<16} {field} = {value!r}")
        if quote:
            print(f"  {'':<16}   from: \"{quote[:100]}\"")
    print("  Worth a glance before uploading — these are the only guessed values.")


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
