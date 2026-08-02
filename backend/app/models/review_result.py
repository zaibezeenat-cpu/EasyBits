from pydantic import BaseModel
from typing import Optional

class SeoCheckResult(BaseModel):
    check_name: str    # e.g. "product_name_length"
    passed: bool
    detail: str

class ReviewResult(BaseModel):
    passed: bool
    preflight_score: int              # 0-100
    checks: list[SeoCheckResult]      # all 13 checks (v3.1 adds content_length_minimum)
    warranty_consistent: bool         # 4-location match
    fact_cross_check_passed: bool
    fact_cross_check_notes: list[str]
    failure_summary: Optional[str] = None
