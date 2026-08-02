from pydantic import BaseModel
from typing import Literal

FailureCategory = Literal[
    "source_unreachable", "no_reliable_source_found", "spec_conflict", "variant_shaped",
    "sku_collision", "writer_reviewer_exhausted", "preflight_score_low",
    "missing_category_schema", "missing_taxonomy_match", "other",
    # V8.0 Production Lock additions
    "brand_casing_mismatch", "production_lock_violation",
    # The supplied warranty contradicts what the scraped sources state. Kept
    # distinct from spec_conflict because warranty is a legally binding claim the
    # business must honour, and reviewers need to spot it immediately in the queue.
    "warranty_conflict",
    # A source served an anti-bot / CAPTCHA challenge instead of the product. Kept
    # distinct from source_unreachable so the reviewer knows the fix is to paste
    # the product's Details, not that the product is simply unlisted.
    "source_blocked",
]

class FailureInfo(BaseModel):
    category: FailureCategory
    detail: str
    context: dict[str, str] = {}
