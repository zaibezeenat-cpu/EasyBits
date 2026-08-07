from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class Brand(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    name: str                              # exact WooCommerce Brands taxonomy term (e.g. "HAIER")
    # Optional display casing for the product TITLE only (e.g. "Haier"). The
    # Brands CSV column always uses `name`; only the title uses this when set.
    # Optional + defaulted so the app works before the migration is applied.
    display_name: str | None = None
    casing_confirmed: bool = False
    is_active: bool = True
    created_at: datetime
    updated_at: datetime

    @property
    def title_name(self) -> str:
        """Brand text for the product title: display casing if set, else the term."""
        return self.display_name or self.name

class Category(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    name: str
    parent_id: UUID | None = None
    is_active: bool = True
    needs_confirmation: bool = True
    notes: str | None = None
    created_at: datetime
    updated_at: datetime

class SpecField(BaseModel):
    """One row of a category's specification table.

    Attributes:
        key: Stable identifier the extractor cites against (e.g. "wattage").
        label: Human-facing name rendered in the spec table.
        required: Whether a product may ship without this field. When True and no
            source states it, the product goes to Manual Review.
        inferable: Whether the Extractor may DEDUCE this value from indirect
            evidence when no source states it outright.

            Defaults False, and that default is the safety property: a field is
            never inferable by accident. Only set it for CATEGORICAL fields whose
            value follows from described features -- a vacuum with "flexible hose,
            extension tube, dust bag" is a canister; a washer with "separate wash
            and spin tubs" is a twin tub.

            NEVER set it for a measurement. There is no evidence from which a
            wattage or a capacity can be deduced, only guessed, and a wrong number
            on a live listing is the failure this whole pipeline exists to prevent.

            A deduced value is cited with confidence="inferred" and never counts
            as confirmed -- see app/builders/fact_corroboration.py.
    """

    key: str
    label: str
    required: bool = True
    inferable: bool = False

class CategorySpecSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    category_id: UUID
    fields: list[SpecField]
    created_at: datetime
    updated_at: datetime
