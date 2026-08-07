from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, field_validator


class RawProductInput(BaseModel):
    sku: str
    model_number: str
    brand_name: str
    category_name: str
    product_type: str                            # e.g. "Air Conditioner" (Phase 2 §3.1)
    regular_price: Decimal
    # None means "no discount" -- assign_prices() returns this deliberately when
    # the sheet carries a single price, so a product with one price is a real,
    # valid state here, not a missing value. Every reader downstream (the CSV
    # assembler, build_product_row) already treats a falsy sale_price as "show
    # no sale price"; this only makes the type honest about that.
    sale_price: Decimal | None = None
    in_stock: bool = True                        # closes #14 — surfaced by StockStatusToggle.tsx
    warranty_override: str | None = None      # phase1.md §5.5's per-product override
    template_choice: Literal["A", "B"] = "A"

    # Operator-provided source (the real Westpoint sheet's "Website Link" + "Details").
    # Both optional: when given, the pipeline uses them as an authoritative source instead
    # of (or, in augment mode, in addition to) search-based discovery. When absent, discovery
    # runs exactly as before -- nothing regresses for products without a link.
    official_url: str | None = None
    source_details: str | None = None

    # The sheet's "Existing ID": when present the product is regenerated with the new logic and
    # the CSV's ID column is filled so WooCommerce updates that product in place (no duplicate).
    # Absent -> a brand-new product is created. Auto-detected; no separate mode to manage.
    existing_id: str | None = None

    # Holds all non-core columns from the input CSV (e.g., "Images", "Tax class") to pass through
    # to the final CSV output. See csv_assembler.py for overlay logic.
    passthrough_columns: dict[str, Any] | None = None

    @field_validator("existing_id", mode="before")
    @classmethod
    def _validate_existing_id(cls, v):
        """
        A blank cell means "create new" -> None. A present value MUST be a positive
        integer (a real WooCommerce product id): this both blocks CSV-formula
        injection ("=1+1") into the ID column and prevents a malformed id -- which
        was meant to UPDATE -- from silently becoming a DUPLICATE product. An
        invalid id is rejected loudly rather than dropped.
        """
        if v is None:
            return None
        s = str(v).strip()
        if not s:
            return None
        if not s.isdigit() or int(s) <= 0:
            raise ValueError(
                f"existing_id must be a positive WooCommerce product id, got {v!r}"
            )
        return s
