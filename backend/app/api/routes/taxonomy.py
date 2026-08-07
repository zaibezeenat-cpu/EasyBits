from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from app.db.repositories.audit import audit_repo
from app.db.repositories.brands import brands_repo
from app.db.repositories.categories import categories_repo
from app.models.taxonomy import Brand, Category

router = APIRouter()


async def _assert_taxonomy_name_is_new(name: str, *, kind: str) -> None:
    """
    Rejects a taxonomy name that collides with an existing brand or category.

    WHY BOTH TABLES ARE CHECKED, NOT JUST THE ONE BEING WRITTEN
    -----------------------------------------------------------
    A brand and a category are different things in WooCommerce and must never
    hold the same term. "Deerma" was seeded into the category tree by mistake --
    it is a manufacturer -- and nothing in the system objected, because creation
    had no validation at all. It sat in live taxonomy until a manual audit found
    it.

    WHY THE COMPARISON IS CASE-INSENSITIVE WHILE EVERYTHING DOWNSTREAM IS
    CASE-SENSITIVE: those two rules point the same way. WooCommerce matches
    terms by exact string, so "Air conditioner" and "air conditioner" become two
    separate categories. The export locks refuse a casing that does not match
    live taxonomy exactly; this refuses to CREATE the near-duplicate that would
    make two valid-looking casings exist in the first place.
    """
    candidate = name.strip().casefold()

    for existing in await brands_repo.list():
        if existing.name.strip().casefold() == candidate:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"'{name.strip()}' already exists as a brand ('{existing.name}'). "
                    f"A brand and a category must never share a term."
                    if kind == "category"
                    else f"Brand '{existing.name}' already exists. To change its casing, "
                         f"edit it — creating a second entry would split the catalogue "
                         f"across two terms in WooCommerce."
                ),
            )

    for existing in await categories_repo.list():
        if existing.name.strip().casefold() == candidate:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"'{name.strip()}' already exists as a category ('{existing.name}'). "
                    f"A brand and a category must never share a term."
                    if kind == "brand"
                    else f"Category '{existing.name}' already exists. To change its casing, "
                         f"edit it — creating a second entry would split the catalogue "
                         f"across two terms in WooCommerce."
                ),
            )


class BrandCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class BrandUpdate(BaseModel):
    casing_confirmed: bool | None = None
    is_active: bool | None = None
    # Display casing for the product title only (e.g. "Haier"). Send "" to clear.
    display_name: str | None = Field(default=None, max_length=120)


class CategoryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    parent_id: UUID | None = None


class CategoryUpdate(BaseModel):
    parent_id: UUID | None = None
    is_active: bool | None = None
    needs_confirmation: bool | None = None
    notes: str | None = None


@router.get("/brands", response_model=list[Brand])
async def list_brands():
    return await brands_repo.list()


@router.post("/brands", response_model=Brand)
async def create_brand(payload: BrandCreate):
    # Stored stripped: " Kenwood" and "Kenwood" are different WooCommerce terms,
    # and trailing whitespace is invisible in the UI that created it.
    name = payload.name.strip()
    await _assert_taxonomy_name_is_new(name, kind="brand")
    created = await brands_repo.create({"name": name})
    # A new brand becomes a new WooCommerce term on the next export, so it is
    # exactly the kind of change worth being able to trace back later.
    await audit_repo.log_event(event_type="brand_created", payload={"name": name}, actor="operator")
    return created


@router.patch("/brands/{brand_id}", response_model=Brand)
async def update_brand(brand_id: UUID, payload: BrandUpdate):
    """
    Confirm casing against the live WooCommerce taxonomy (§0 item 3), or
    deactivate a brand -- both live edits, no code change or redeploy needed.
    """
    data = payload.model_dump(exclude_unset=True)
    if "display_name" in data:
        # Empty string clears the override (title falls back to the taxonomy term).
        data["display_name"] = (data["display_name"] or "").strip() or None
    updated = await brands_repo.update(brand_id, data)
    if not updated:
        raise HTTPException(status_code=404, detail="Brand not found")
    return updated


@router.get("/categories", response_model=list[Category])
async def list_categories():
    return await categories_repo.list()


@router.post("/categories", response_model=Category)
async def create_category(payload: CategoryCreate):
    name = payload.name.strip()
    await _assert_taxonomy_name_is_new(name, kind="category")
    data = {"name": name}
    if payload.parent_id:
        data["parent_id"] = str(payload.parent_id)
    created = await categories_repo.create(data)
    await audit_repo.log_event(
        event_type="category_created",
        payload={"name": name, "parent_id": str(payload.parent_id) if payload.parent_id else None},
        actor="operator",
    )
    return created


@router.patch("/categories/{category_id}", response_model=Category)
async def update_category(category_id: UUID, payload: CategoryUpdate):
    """
    Set the real parent (confirming phase1.md §9.2's mapping), flip
    needs_confirmation once verified against the live category tree, or
    deactivate/annotate a category (e.g. "Item"/"Inverter") -- all live edits.
    """
    data = payload.model_dump(exclude_unset=True)
    if "parent_id" in data and data["parent_id"] is not None:
        data["parent_id"] = str(data["parent_id"])
    updated = await categories_repo.update(category_id, data)
    if not updated:
        raise HTTPException(status_code=404, detail="Category not found")
    return updated
