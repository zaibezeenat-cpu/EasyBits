from uuid import UUID

from fastapi import APIRouter, HTTPException

from app.db.repositories.templates import templates_repo
from app.models.template import Template, TemplateCreate, TemplateUpdate

router = APIRouter()


@router.get("/", response_model=list[Template])
async def list_templates():
    return await templates_repo.list()


@router.get("/{template_id}", response_model=Template)
async def get_template(template_id: UUID):
    template = await templates_repo.get(template_id)
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    return template


@router.post("/", response_model=Template)
async def create_template(payload: TemplateCreate):
    return await templates_repo.create(payload.model_dump())


@router.patch("/{template_id}", response_model=Template)
async def update_template(template_id: UUID, payload: TemplateUpdate):
    return await templates_repo.update(template_id, payload.model_dump(exclude_unset=True))
