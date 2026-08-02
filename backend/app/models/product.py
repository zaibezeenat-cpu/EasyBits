from pydantic import BaseModel, ConfigDict
from typing import Any, Optional
from datetime import datetime
from uuid import UUID
from enum import Enum
from decimal import Decimal

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
    model_number: Optional[str] = None
    raw_input: Optional[dict[str, Any]] = None
    status: ProductStatus = ProductStatus.QUEUED
    variant_shaped: bool = False
    
    brand_id: Optional[UUID] = None
    category_id: Optional[UUID] = None
    template_long_desc_id: Optional[UUID] = None
    
    image_count: int = 0
    scraped_image_urls: list[str] = []
    
    name: Optional[str] = None
    short_description: Optional[str] = None
    description: Optional[str] = None
    specs_table_html: Optional[str] = None
    
    rank_math_focus_keyword: Optional[str] = None
    rank_math_title: Optional[str] = None
    rank_math_description: Optional[str] = None
    
    weight_kg: Decimal = Decimal("0.0")
    length_cm: Decimal = Decimal("0.0")
    width_cm: Decimal = Decimal("0.0")
    height_cm: Decimal = Decimal("0.0")
    
    regular_price: Optional[Decimal] = None
    sale_price: Optional[Decimal] = None
    in_stock: bool = True
    
    warranty_override: Optional[str] = None
    resolved_warranty_phrase: Optional[str] = None
    price_discrepancy_pct: Optional[Decimal] = None
    
    extraction_result: dict[str, Any] = {}
    writer_result: dict[str, Any] = {}
    review_result: dict[str, Any] = {}
    
    preflight_score: int = 0
    retry_count: int = 0
    
    failure_reason: Optional[str] = None
    failure_detail: dict[str, Any] = {}
    
    csv_row: dict[str, Any] = {}
    
    queued_at: datetime
    ready_for_qa_at: Optional[datetime] = None
    approved_at: Optional[datetime] = None
    approved_by: Optional[str] = None
    exported_at: Optional[datetime] = None
    
    created_at: datetime
    updated_at: datetime


class ProductUpdate(BaseModel):
    """Partial update payload for PATCH /api/products/{id} — used by the QA Panel's
    Approve/Reject/Manual-Review actions and by future inline field corrections."""
    status: Optional[ProductStatus] = None
    approved_by: Optional[str] = None
    short_description: Optional[str] = None
    description: Optional[str] = None
    regular_price: Optional[Decimal] = None
    sale_price: Optional[Decimal] = None
    warranty_override: Optional[str] = None
