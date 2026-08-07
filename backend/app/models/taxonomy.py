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
    key: str
    label: str
    required: bool = True

class CategorySpecSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    category_id: UUID
    fields: list[SpecField]
    created_at: datetime
    updated_at: datetime
