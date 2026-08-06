import logging

from app.core.domain_utils import InvalidDomainError, normalize_domain
from app.db.repositories.audit import audit_repo
from app.db.repositories.sources import sources_repo
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter()


class TrustedSourceCreate(BaseModel):
    domain: str = Field(min_length=1, max_length=255)
    label: str = Field(min_length=1, max_length=120)
    priority: int = Field(default=0, ge=0, le=999)


class TrustedSourceUpdate(BaseModel):
    """
    Both fields optional so one PATCH can toggle, reprioritise, or do both.
    An all-None body is rejected rather than treated as a no-op success --
    a request that changes nothing but reports 200 reads as a saved edit.
    """
    is_active: bool | None = None
    priority: int | None = Field(default=None, ge=0, le=999)


class SourceOrder(BaseModel):
    """Full ordered list of source ids, first = highest priority."""
    source_ids: list[str] = Field(min_length=1, max_length=200)


class BrandDomainUpdate(BaseModel):
    official_domain: str = Field(min_length=1, max_length=255)


@router.get("/trusted-secondary")
async def list_trusted_secondary_sources():
    """Settings -> Trusted Secondary Sources (phase2.md §5.2). Seeded with Japan
    Electronics/Surmawala by default, but this list is fully admin-editable --
    add/remove/deactivate without a code change or redeploy."""
    return await sources_repo.list_all_trusted_secondary_sources()


@router.post("/trusted-secondary")
async def add_trusted_secondary_source(payload: TrustedSourceCreate):
    try:
        domain = normalize_domain(payload.domain)
    except InvalidDomainError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
    return await sources_repo.create_trusted_secondary_source(domain, payload.label.strip(), payload.priority)


@router.patch("/trusted-secondary/{source_id}")
async def update_trusted_secondary_source(source_id: str, payload: TrustedSourceUpdate):
    if payload.is_active is None and payload.priority is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provide is_active, priority, or both.",
        )

    result = None
    if payload.priority is not None:
        try:
            result = await sources_repo.set_trusted_secondary_source_priority(source_id, payload.priority)
        except ValueError as e:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
    if payload.is_active is not None:
        result = await sources_repo.set_trusted_secondary_source_active(source_id, payload.is_active)
    return result


@router.put("/trusted-secondary/order")
async def reorder_trusted_secondary_sources(payload: SourceOrder):
    """
    Rewrites priorities from a full ordered list (first = tried first).

    Takes the WHOLE list rather than a single move. Sending one item's new
    index would leave the others' priorities stale, producing duplicate values
    and an order that depends on the database's tiebreak rather than what the
    operator dragged on screen.
    """
    if len(set(payload.source_ids)) != len(payload.source_ids):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The same source appears more than once in the order.",
        )

    updated = []
    for index, source_id in enumerate(payload.source_ids):
        try:
            updated.append(await sources_repo.set_trusted_secondary_source_priority(source_id, index))
        except ValueError as e:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Source '{source_id}' no longer exists. Reload the list and try again.",
            ) from e
    logger.info(f"Reordered {len(updated)} trusted secondary source(s)")
    await audit_repo.log_event(
        event_type="sources_reordered",
        payload={"order": list(payload.source_ids)},
        actor="operator",
    )
    return updated


@router.get("/brand-domains")
async def list_brand_domains():
    """
    Map of brand_id -> official domain.

    A brand missing from this map has no official site configured, which means
    tier 2 of source discovery is skipped for it entirely. The Taxonomy Manager
    shows that gap explicitly rather than letting it pass as normal.
    """
    return await sources_repo.list_brand_domains()


@router.put("/brand-domains/{brand_id}")
async def set_brand_domain(brand_id: str, payload: BrandDomainUpdate):
    try:
        domain = normalize_domain(payload.official_domain)
    except InvalidDomainError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e

    result = await sources_repo.set_brand_domain(brand_id, domain)
    logger.info(f"Brand {brand_id} official domain set to '{domain}'")
    # Changing where a brand's facts come from changes what future descriptions
    # say, so the old value is recorded alongside the new one.
    await audit_repo.log_event(
        event_type="brand_domain_set",
        payload={"brand_id": brand_id, "official_domain": domain, "submitted": payload.official_domain},
        actor="operator",
    )
    return result


@router.delete("/brand-domains/{brand_id}", status_code=status.HTTP_204_NO_CONTENT)
async def clear_brand_domain(brand_id: str) -> None:
    await sources_repo.clear_brand_domain(brand_id)
    # Removing a domain silently disables tier 2 for that brand.
    await audit_repo.log_event(
        event_type="brand_domain_cleared", payload={"brand_id": brand_id}, actor="operator"
    )
