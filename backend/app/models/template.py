from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class Template(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    template_type: Literal["short_description", "long_description_a", "long_description_b", "specs_table"]
    name: str
    html_skeleton: str
    is_default: bool = False
    is_active: bool = True
    version: int = 1
    created_at: datetime
    updated_at: datetime


class TemplateCreate(BaseModel):
    template_type: Literal["short_description", "long_description_a", "long_description_b", "specs_table"]
    name: str
    html_skeleton: str
    is_default: bool = False


class TemplateUpdate(BaseModel):
    name: str | None = None
    html_skeleton: str | None = None
    is_active: bool | None = None
