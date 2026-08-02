from pydantic import BaseModel
from uuid import UUID
from typing import Literal, Optional
from app.models.raw_input import RawProductInput
from app.models.taxonomy import CategorySpecSchema
from app.models.extraction import ExtractionResult
from app.models.writer_output import WriterOutput
from app.models.review_result import ReviewResult
from app.models.dimensions import DimensionsResult
from app.models.failure import FailureInfo

class PipelineState(BaseModel):
    product_id: UUID
    batch_id: UUID
    raw_input: RawProductInput
    category_schema: Optional[CategorySpecSchema] = None
    variant_shaped: bool = False
    # How other sellers title this model, harvested during scraping. Feeds the
    # series/feature words in the product title, but only terms corroborated
    # across multiple sources are ever used.
    competitor_titles: list[str] = []
    extraction: Optional[ExtractionResult] = None
    selected_template_type: Literal["A", "B"] = "A"
    writer_output: Optional[WriterOutput] = None
    review_result: Optional[ReviewResult] = None
    dimensions: Optional[DimensionsResult] = None

    # Deterministic Builder Outputs
    name: Optional[str] = None
    tags: Optional[str] = None
    short_description: Optional[str] = None
    description: Optional[str] = None
    specs_table_html: Optional[str] = None
    resolved_warranty_phrase: Optional[str] = None
    price_discrepancy_pct: Optional[float] = None

    # V8.0 Production Lock — deterministic SEO fields (no longer written by the LLM)
    rank_math_focus_keyword: Optional[str] = None   # PRIMARY = short brand+model (density target)
    rank_math_secondary_keyword: Optional[str] = None  # 2nd keyword = model+type (before LSI)
    rank_math_title: Optional[str] = None           # "Boss Title Rule" / power-word builder output
    meta_description_cta: Optional[str] = None      # resolved ONCE (writer_node) w/ real capacity;
                                                     # reviewer_node reuses this exact string, never
                                                     # recomputes it, so it can't silently drift

    retry_count: int = 0
    failure: Optional[FailureInfo] = None
    manual_review_required: bool = False
    csv_row: Optional[dict] = None
