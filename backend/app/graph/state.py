from typing import Literal
from uuid import UUID

from app.models.dimensions import DimensionsResult
from app.models.extraction import ExtractionResult
from app.models.failure import FailureInfo
from app.models.raw_input import RawProductInput
from app.models.review_result import ReviewResult
from app.models.taxonomy import CategorySpecSchema
from app.models.writer_output import WriterOutput
from pydantic import BaseModel


class PipelineState(BaseModel):
    product_id: UUID
    batch_id: UUID
    raw_input: RawProductInput
    category_schema: CategorySpecSchema | None = None
    variant_shaped: bool = False
    # How other sellers title this model, harvested during scraping. Feeds the
    # series/feature words in the product title, but only terms corroborated
    # across multiple sources are ever used.
    competitor_titles: list[str] = []
    extraction: ExtractionResult | None = None
    selected_template_type: Literal["A", "B"] = "A"
    writer_output: WriterOutput | None = None
    review_result: ReviewResult | None = None
    dimensions: DimensionsResult | None = None

    # Deterministic Builder Outputs
    name: str | None = None
    tags: str | None = None
    short_description: str | None = None
    description: str | None = None
    specs_table_html: str | None = None
    resolved_warranty_phrase: str | None = None
    price_discrepancy_pct: float | None = None

    # V8.0 Production Lock — deterministic SEO fields (no longer written by the LLM)
    rank_math_focus_keyword: str | None = None   # PRIMARY = short brand+model (density target)
    rank_math_secondary_keyword: str | None = None  # 2nd keyword = model+type (before LSI)
    rank_math_title: str | None = None           # "Boss Title Rule" / power-word builder output
    meta_description_cta: str | None = None      # resolved ONCE (writer_node) w/ real capacity;
                                                     # reviewer_node reuses this exact string, never
                                                     # recomputes it, so it can't silently drift

    retry_count: int = 0
    failure: FailureInfo | None = None
    manual_review_required: bool = False
    csv_row: dict | None = None
