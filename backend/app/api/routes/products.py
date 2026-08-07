from decimal import Decimal
from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.builders.category_classifier import llm_pick_category
from app.builders.input_adapter import parse_sheet_row
from app.db.repositories.brands import brands_repo
from app.db.repositories.categories import categories_repo
from app.db.repositories.citations import citations_repo
from app.db.repositories.products import products_repo
from app.models.product import Product, ProductUpdate
from app.models.raw_input import RawProductInput

router = APIRouter()


class SheetRowInput(BaseModel):
    """
    One row of the real input spreadsheet:
        S.No | Product Name | Regular Price | Sale Price | Warranty | Status

    price_a / price_b are the two price cells IN SHEET ORDER. Their regular-vs-sale
    roles are derived from the values, never from the column headers -- in the real
    sheet the "Regular Price" column holds the lower selling price, so trusting the
    labels publishes a price increase as a discount. See input_adapter.assign_prices.
    """
    product_name: str
    price_a: Decimal
    price_b: Decimal
    warranty: str | None = None
    status: str | None = None


class SheetRowPreview(BaseModel):
    """Result of parsing one row, before anything is written."""
    product_name: str
    sku: str | None = None
    model_number: str | None = None
    brand_name: str | None = None
    category_name: str | None = None
    category_path: str | None = None
    regular_price: Decimal
    sale_price: Decimal | None = None
    warranty_phrase: str | None = None
    template_choice: str | None = None
    missing_required: list[str] = []
    ready: bool = False


@router.post("/parse-sheet", response_model=list[SheetRowPreview])
async def parse_sheet(rows: list[SheetRowInput]):
    """
    Parses pasted spreadsheet rows and returns what the system resolved, WITHOUT
    creating anything. Powers the bulk-import preview so prices, SKUs, brands and
    categories can be eyeballed before any product row exists.

    Brand and category lists are read live from the taxonomy tables on every
    call, so anything added or edited in the frontend Taxonomy Manager is picked
    up immediately without a redeploy.
    """
    known_brands = await brands_repo.get_active_names()
    known_categories, category_parents = await categories_repo.get_active_names_and_parents()

    previews: list[SheetRowPreview] = []
    for row in rows:
        try:
            parsed = parse_sheet_row(
                product_name=row.product_name,
                price_a=row.price_a,
                price_b=row.price_b,
                warranty_text=row.warranty,
                status_text=row.status,
                known_brands=known_brands,
                known_categories=known_categories,
                category_parents=category_parents,
            )
        except ValueError as e:
            # Invalid prices (zero/negative) — surface the row, don't abort the batch.
            previews.append(SheetRowPreview(
                product_name=row.product_name,
                regular_price=max(row.price_a, row.price_b),
                missing_required=[str(e)],
                ready=False,
            ))
            continue

        # Hybrid category resolution: deterministic name-matching ran inside
        # parse_sheet_row (free, exact for appliances that name themselves). When
        # it found nothing (e.g. a hair straightener -> "Beauty", whose name never
        # appears in the title), fall back to the LLM, which picks ONLY from the
        # live category list or nothing. This LLM call happens only for the
        # unmatched rows, so a bulk paste stays cheap.
        if parsed.category_name is None:
            llm_category = await llm_pick_category(row.product_name, known_categories)
            if llm_category:
                parsed.category_name = llm_category
                parsed.category_parent = category_parents.get(llm_category)

        missing = parsed.missing_required()
        previews.append(SheetRowPreview(
            product_name=parsed.product_name,
            sku=parsed.sku,
            model_number=parsed.model_number,
            brand_name=parsed.brand_name,
            category_name=parsed.category_name,
            category_path=parsed.category_path,
            regular_price=parsed.regular_price,
            sale_price=parsed.sale_price,
            warranty_phrase=parsed.warranty_phrase,
            template_choice=parsed.template_choice,
            missing_required=missing,
            ready=not missing,
        ))
    return previews

@router.get("/", response_model=list[Product])
async def list_products(status: str | None = None):
    """Powers the Products index page and the Dashboard's stat-card links."""
    filters = {"status": status} if status else {}
    return await products_repo.list(filters=filters)

def build_product_row(batch_id: UUID, raw_input: RawProductInput) -> dict[str, Any]:
    """
    Maps a RawProductInput onto a `products` insert row. Shared by single create
    (Quick-Add) and the bulk import endpoint so both persist identical shapes --
    including the new optional operator source / existing_id fields carried inside
    `raw_input` (model_dump), which the pipeline reads back later.
    """
    return {
        "batch_id": str(batch_id),
        "sku": raw_input.sku,
        "model_number": raw_input.model_number,
        "raw_input": raw_input.model_dump(mode="json"),
        "regular_price": float(raw_input.regular_price),
        "sale_price": float(raw_input.sale_price),
        "in_stock": raw_input.in_stock,
        "warranty_override": raw_input.warranty_override,
    }


@router.post("/", response_model=Product)
async def create_product(batch_id: UUID, raw_input: RawProductInput):
    """
    Creates a queued product row under a batch. Used by Quick-Add (batch created
    with auto_run=False, product added here, then POST /api/batches/{id}/run
    triggers the pipeline) and will also back a future bulk-paste import.
    """
    return await products_repo.create(build_product_row(batch_id, raw_input))

@router.get("/batch/{batch_id}", response_model=list[Product])
async def list_products_by_batch(batch_id: UUID):
    return await products_repo.get_by_batch(batch_id)

@router.get("/{product_id}", response_model=Product)
async def get_product(product_id: UUID):
    product = await products_repo.get(product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    return product

@router.get("/{product_id}/citations")
async def get_product_citations(product_id: UUID):
    """Source citations for the QA Panel's Full Review Mode (phase1.md §5.2)."""
    return await citations_repo.get_by_product(str(product_id))

@router.patch("/{product_id}", response_model=Product)
async def update_product(product_id: UUID, update: ProductUpdate):
    return await products_repo.update_product(product_id, update.model_dump(exclude_unset=True))
