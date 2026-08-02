from pydantic import BaseModel, model_validator
from datetime import datetime
from typing import Literal, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from app.models.taxonomy import CategorySpecSchema

# "web" = an unvetted page discovered via broad Google search (lowest trust);
# accepted only with corroboration or under priority source-mode.
SourceType = Literal["official", "trusted_secondary", "web", "user_estimate"]
Confidence = Literal["confirmed", "conflicting", "unreachable"]

class SourceCitation(BaseModel):
    field_name: str                    # matches SpecField.key
    value: str                         # literal "UNKNOWN" allowed
    source_url: Optional[str] = None   # None only when confidence == "unreachable"
    source_type: SourceType
    confidence: Confidence
    fetched_at: datetime

    @model_validator(mode="after")
    def unknown_implies_unreachable_or_null_url(self):
        if self.value == "UNKNOWN" and self.confidence == "confirmed":
            raise ValueError("value='UNKNOWN' cannot have confidence='confirmed' — no-hallucination contract violation (phase1.md §5.2)")
        return self

class ExtractionResult(BaseModel):
    product_id: str
    category_key: str
    citations: list[SourceCitation]     # 1+ per field_name
    image_urls: list[str] = []
    # BUG FIX (Phase 3 integration test, real Groq call): Decimal's Pydantic JSON
    # schema emits a regex `pattern` that Groq's structured-output tool-schema
    # validator rejects outright ("is not valid 'regex'"), breaking the
    # Extractor's Groq fallback path every time it's needed. Never consumed as
    # a Decimal anywhere downstream, so float is strictly safer here.
    scraped_official_price: Optional[float] = None

    def resolve(self, field_name: str):
        """
        Cross-source resolution for one field (see fact_corroboration).

        Imported lazily to keep the dependency one-directional
        (fact_corroboration is deliberately independent of this model).
        """
        from app.builders.fact_corroboration import resolve_field
        return resolve_field(field_name, self.citations)

    def confirmed_value(self, field_name: str) -> Optional[str]:
        """
        The value to use downstream, resolved across ALL sources.

        A value is trusted ONLY when it is corroborated -- an official brand
        source states it, OR two or more independent sources agree. A value that
        rests on a SINGLE unverified retailer (status "single_source") is NOT
        returned: the whole point of the system is multi-source cross-checking,
        and one retailer stating "capacity 346" with nothing to compare it
        against is exactly the error that must be caught, not published.

        (Also fixes the earlier latent bug where two agreeing sources cancelled
        out and the field looked missing -- agreement now confirms.)
        """
        r = self.resolve(field_name)
        return r.value if r.is_confirmed else None

    def single_source_value(self, field_name: str) -> Optional[str]:
        """The value when it rests on exactly one unverified source, else None.

        Used only to explain an escalation ("known from one source but not
        corroborated"), never to publish.
        """
        r = self.resolve(field_name)
        return r.value if r.status == "single_source" else None

    def has_conflict(self, field_name: str) -> bool:
        """
        True only for a real disagreement between comparably-trusted sources.

        Compares NORMALISED values, so "9 Cu Ft" vs "9 cubic feet" is no longer
        a false conflict; and an official source outranking a lone retailer is a
        resolution, not a conflict.
        """
        return self.resolve(field_name).status == "conflict"

    def uncorroborated_required_fields(self, schema: "CategorySpecSchema") -> dict[str, str]:
        """
        Required fields that are NOT safe to publish, mapped to why:
        "single_source" (one unverified source) or "conflict" (sources disagree).
        Distinct from `missing_required_fields` (no source states them at all),
        so the review queue can show the real reason.
        """
        issues: dict[str, str] = {}
        for f in schema.fields:
            if not f.required:
                continue
            status = self.resolve(f.key).status
            if status in ("single_source", "conflict"):
                issues[f.key] = status
        return issues

    def missing_required_fields(self, schema: "CategorySpecSchema") -> list[str]:
        return [f.key for f in schema.fields if f.required and self.confirmed_value(f.key) is None
                and not self.has_conflict(f.key)]

    def conflicting_fields(self, schema: "CategorySpecSchema") -> list[str]:
        return [f.key for f in schema.fields if self.has_conflict(f.key)]
