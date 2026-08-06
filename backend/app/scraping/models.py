
from pydantic import BaseModel


class ScrapeResult(BaseModel):
    url: str
    content: str  # cleaned plain text, ready for an LLM prompt
    engine_used: str  # "firecrawl" or "playwright"
    success: bool
    error_message: str | None = None
    metadata: dict = {}
    # Product-detail links found on the page. A search-results page proves the
    # product exists but rarely carries its specs, so the orchestrator follows
    # these to the detail page where the real facts live.
    product_links: list[str] = []
    # How other sellers title this exact model. Used to harvest the series and
    # feature wording customers actually search for, but only terms corroborated
    # across multiple sources ever reach a product title.
    candidate_titles: list[str] = []
