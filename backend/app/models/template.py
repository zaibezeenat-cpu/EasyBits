from pydantic import BaseModel, ConfigDict
from uuid import UUID
from datetime import datetime
from typing import Optional, Literal


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
    name: Optional[str] = None
    html_skeleton: Optional[str] = None
    is_active: Optional[bool] = None
