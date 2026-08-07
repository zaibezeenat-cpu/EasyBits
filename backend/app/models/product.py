from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class ProductStatus(str, Enum):
    QUEUED = "queued"
    SCRAPING = "scraping"
    EXTRACTING = "extracting"
    WRITING = "writing"
    REVIEWING = "reviewing"
    READY_FOR_QA = "ready_for_qa"
    MANUAL_REVIEW = "manual_review"
    APPROVED = "approved"
    EXPORTED = "exported"
    FAILED = "failed"

class Product(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    batch_id: UUID
    sku: str
    model_number: str | None = None
    raw_input: dict[str, Any] | None = None
    status: ProductStatus = ProductStatus.QUEUED
    variant_shaped: bool = False
    
    brand_id: UUID | None = None
    category_id: UUID | None = None
    template_long_desc_id: UUID | None = None
    
    image_count: int = 0
    scraped_image_urls: list[str] = []
    
    name: str | None = None
    short_description: str | None = None
    description: str | None = None
    specs_table_html: str | None = None
    
    rank_math_focus_keyword: str | None = None
    rank_math_title: str | None = None
    rank_math_description: str | None = None
    
    weight_kg: Decimal = Decimal("0.0")
    length_cm: Decimal = Decimal("0.0")
    width_cm: Decimal = Decimal("0.0")
    height_cm: Decimal = Decimal("0.0")
    
    regular_price: Decimal | None = None
    sale_price: Decimal | None = None
    in_stock: bool = True
    
    warranty_override: str | None = None
    resolved_warranty_phrase: str | None = None
    price_discrepancy_pct: Decimal | None = None
    
    extraction_result: dict[str, Any] = {}
    writer_result: dict[str, Any] = {}
    review_result: dict[str, Any] = {}
    
    preflight_score: int = 0
    retry_count: int = 0
    
    failure_reason: str | None = None
    failure_detail: dict[str, Any] = {}
    
    csv_row: dict[str, Any] = {}
    
    queued_at: datetime
    ready_for_qa_at: datetime | None = None
    approved_at: datetime | None = None
    approved_by: str | None = None
    exported_at: datetime | None = None
    
    created_at: datetime
    updated_at: datetime


class ProductUpdate(BaseModel):
    """Partial update payload for PATCH /api/products/{id} — used by the QA Panel's
    Approve/Reject/Manual-Review actions and by future inline field corrections."""
    status: ProductStatus | None = None
    approved_by: str | None = None
    short_description: str | None = None
    description: str | None = None
    regular_price: Decimal | None = None
    sale_price: Decimal | None = None
    warranty_override: str | None = None
