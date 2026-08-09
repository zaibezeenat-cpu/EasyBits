from datetime import datetime
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, model_validator

if TYPE_CHECKING:
    from app.models.taxonomy import CategorySpecSchema

# "web" = an unvetted page discovered via broad Google search (lowest trust);
# accepted only with corroboration or under priority source-mode.
SourceType = Literal["official", "trusted_secondary", "web", "user_estimate"]

# "inferred" = the value was DEDUCED from described features rather than stated
# outright ("flexible hose, extension tube, dust bag" -> canister vacuum). It is a
# separate level on purpose: an inference must never be able to wear the
# "confirmed" badge, because every downstream guard keys off that. Only fields the
# category schema marks `inferable` may carry it -- enforced in code, not merely
# asked for in the prompt.
Confidence = Literal["confirmed", "conflicting", "unreachable", "inferred"]

class SourceCitation(BaseModel):
    field_name: str                    # matches SpecField.key
    value: str                         # literal "UNKNOWN" allowed
    source_url: str | None = None   # None only when confidence == "unreachable"
    source_type: SourceType
    confidence: Confidence
    fetched_at: datetime
    # The words the value rests on. Required for an inferred citation: it is the
    # only thing separating a defensible deduction from a guess, and it is what
    # the operator reads in the CLI report before shipping the CSV.
    exact_quote: str | None = None

    @model_validator(mode="after")
    def unknown_implies_unreachable_or_null_url(self):
        if self.value == "UNKNOWN" and self.confidence == "confirmed":
            raise ValueError("value='UNKNOWN' cannot have confidence='confirmed' — no-hallucination contract violation (phase1.md §5.2)")
        return self

    @model_validator(mode="after")
    def inferred_requires_evidence(self):
        """An inference with nothing behind it is a guess wearing a label.

        The quote is what makes a deduction reviewable -- without it neither the
        operator nor a later audit can tell whether "Canister" followed from the
        source text or was simply produced.
        """
        if self.confidence == "inferred":
            if self.value == "UNKNOWN":
                raise ValueError("confidence='inferred' with value='UNKNOWN' is meaningless")
            if not (self.exact_quote or "").strip():
                raise ValueError(
                    "confidence='inferred' requires exact_quote -- the evidence the "
                    "deduction rests on. An inference without evidence is a guess."
                )
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
    scraped_official_price: float | None = None

    def resolve(self, field_name: str):
        """
        Cross-source resolution for one field (see fact_corroboration).

        Imported lazily to keep the dependency one-directional
        (fact_corroboration is deliberately independent of this model).
        """
        from app.builders.fact_corroboration import resolve_field
        return resolve_field(field_name, self.citations)

    def confirmed_value(self, field_name: str) -> str | None:
        """
        The value to use downstream, resolved across ALL sources.

        2026-08-09 (owner-directed relaxation): a value backed by exactly ONE
        source -- official OR a single trusted retailer -- is now accepted and
        published. The prior two-source rule assumed corroboration would
        usually be available; in practice most brands have no registered
        official domain (brand_domain_aliases is deliberately not
        auto-populated, see source_discovery.py) and only 1-2 trusted retailers
        are configured, so getting two independent sources to state the exact
        same spec rarely happened -- nearly every required field landed in
        Manual Review even when the one source that did state it was correct.

        Still refused, on purpose:
          - a field NO source states at all (status "unknown")
          - a field where sources genuinely DISAGREE (status "conflict")
        Both remain real reasons to hold a product; an uncontested single
        source is no longer one of them. `single_source_value()` below and the
        citation's `confidence`/`source_type` are still stored and shown in the
        QA panel, so a single-retailer fact stays visibly less certain than a
        corroborated one -- it just no longer blocks the product outright.
        """
        r = self.resolve(field_name)
        return r.value if r.status in ("confirmed", "corroborated", "single_source") else None

    def single_source_value(self, field_name: str) -> str | None:
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

    def inferred_value(self, field_name: str) -> str | None:
        """The value DEDUCED for this field, or None if it was not deduced.

        Deliberately separate from `confirmed_value`: a caller has to ask for an
        inference by name, so no existing code starts consuming deductions by
        accident when this feature lands.
        """
        r = self.resolve(field_name)
        return r.value if r.status == "inferred" else None

    def inference_evidence(self, field_name: str) -> str | None:
        """The quote a deduction rests on, for the operator's CLI report."""
        for c in self.citations:
            if c.field_name == field_name and c.confidence == "inferred":
                return (c.exact_quote or "").strip() or None
        return None

    def drop_disallowed_inferences(self, schema: "CategorySpecSchema") -> list[str]:
        """Discards inferred citations for fields the schema does not allow.

        THE ENFORCEMENT POINT. The prompt is only told which fields are
        inferable; a model that ignores that and deduces a wattage anyway must be
        stopped by code, not trusted. A field absent from the schema entirely is
        also refused -- an inference about something we do not model is noise.

        Args:
            schema: The category's spec schema.

        Returns:
            Field names whose inferred citations were dropped, so the caller can
            log what the model attempted.
        """
        allowed = {f.key for f in schema.fields if f.inferable}
        dropped: list[str] = []
        kept: list[SourceCitation] = []
        for c in self.citations:
            if c.confidence == "inferred" and c.field_name not in allowed:
                dropped.append(c.field_name)
                continue
            kept.append(c)
        if dropped:
            self.citations = kept
        return sorted(set(dropped))

    def inferred_fields(self, schema: "CategorySpecSchema") -> dict[str, str]:
        """Fields whose value came from a deduction, mapped to that value."""
        out: dict[str, str] = {}
        for f in schema.fields:
            value = self.inferred_value(f.key)
            if value:
                out[f.key] = value
        return out

    def uncorroborated_required_fields(self, schema: "CategorySpecSchema") -> dict[str, str]:
        """
        Required fields that are NOT safe to publish, mapped to why.

        2026-08-09: "single_source" no longer escalates (see confirmed_value's
        note) -- only a genuine cross-source "conflict" does. Kept as a dict
        (not a list) for call-site compatibility in nodes.py.
        """
        issues: dict[str, str] = {}
        for f in schema.fields:
            if not f.required:
                continue
            status = self.resolve(f.key).status
            if status == "conflict":
                issues[f.key] = status
        return issues

    def missing_required_fields(self, schema: "CategorySpecSchema") -> list[str]:
        """Required fields no source states, and which could not be deduced either.

        A field marked `inferable` that DID yield a deduction is not missing --
        that is the whole point of the flag. A field not marked inferable is
        missing even if the model tried to deduce it, because
        `drop_disallowed_inferences` will already have discarded that citation.
        """
        return [
            f.key for f in schema.fields
            if f.required
            and self.confirmed_value(f.key) is None
            and not (f.inferable and self.inferred_value(f.key))
            and not self.has_conflict(f.key)
        ]

    def conflicting_fields(self, schema: "CategorySpecSchema") -> list[str]:
        return [f.key for f in schema.fields if self.has_conflict(f.key)]
