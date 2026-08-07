import logging
import os
from typing import Literal

from fastapi import APIRouter, File, HTTPException, UploadFile, status
from pydantic import BaseModel

from app.builders.seo_title_builder import CATEGORY_TITLE_DESCRIPTORS, POWER_WORD_SUFFIX
from app.builders.sku_snapshot_parser import (
    MAX_UPLOAD_BYTES,
    SnapshotParseError,
    parse_sku_csv,
)
from app.db.repositories.audit import audit_repo
from app.db.repositories.settings import settings_repo
from app.db.repositories.sku_snapshot import sku_snapshot_repo

logger = logging.getLogger(__name__)

router = APIRouter()

TrustLevel = Literal["full_review", "quick_review"]

# Whether discovery may look beyond the configured sources.
#   strict   -- ONLY configured sources; anything else escalates to Manual Review
#   priority -- configured sources are tried first, others allowed as a fallback
SourceMode = Literal["strict", "priority"]
SOURCE_MODE_SETTING_KEY = "source_mode"
DEFAULT_SOURCE_MODE: SourceMode = "strict"

# How the pipeline treats an operator-provided source (the sheet's Website Link /
# Details). A DIFFERENT axis from source_mode above (which governs unvetted `web`
# sources during discovery):
#   augment -- use the provided source AND still run discovery to cross-check it
#   strict  -- use ONLY the provided source; run no discovery at all
ProvidedSourceMode = Literal["augment", "strict"]
PROVIDED_SOURCE_MODE_KEY = "provided_source_mode"
DEFAULT_PROVIDED_SOURCE_MODE: ProvidedSourceMode = "augment"


class SnapshotStatus(BaseModel):
    sku_count: int
    last_imported_at: str | None = None


class SnapshotUploadResult(BaseModel):
    success: bool
    count: int
    skipped_rows: int
    had_header: bool
    warnings: list[str] = []


@router.get("/live-sku-snapshot", response_model=SnapshotStatus)
async def get_live_sku_snapshot_status() -> SnapshotStatus:
    """
    How many live SKUs the duplicate-guard currently knows about, and when they
    were last imported. A count of 0 means the guard cannot block anything.
    """
    return SnapshotStatus(
        sku_count=await sku_snapshot_repo.count(),
        last_imported_at=await sku_snapshot_repo.last_imported_at(),
    )


@router.post("/live-sku-snapshot", response_model=SnapshotUploadResult)
async def upload_live_sku_snapshot(file: UploadFile = File(...)) -> SnapshotUploadResult:
    """
    Replaces the live-SKU snapshot from an uploaded CSV (first column = SKU).

    THIS IS THE SYSTEM'S LAST LINE OF DEFENCE. WooCommerce matches imports by
    SKU: if an exported row carries a SKU that already exists on the live store,
    the import does not create a product, it OVERWRITES the existing one. The
    duplicate-SKU guard compares every generated SKU against this snapshot, so
    an empty or stale snapshot means the guard silently passes everything.

    Previously the frontend faked this upload -- it waited 1.5 seconds and
    reported success while the table stayed empty, so the operator believed the
    protection was on when it was entirely off.

    Errors are returned rather than swallowed: a failed upload the user can see
    is far safer than a successful-looking one that stored nothing.
    """
    raw = await file.read()

    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File exceeds the {MAX_UPLOAD_BYTES // 1024 // 1024} MB limit.",
        )

    filename = (file.filename or "").lower()
    if filename and not filename.endswith((".csv", ".txt")):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Please upload a .csv file exported from WooCommerce.",
        )

    try:
        parsed = parse_sku_csv(raw)
    except SnapshotParseError as e:
        # The parser's message names the actual problem (empty file, wrong
        # column, no valid SKUs), which is what the operator needs to fix it.
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e

    try:
        count = await sku_snapshot_repo.replace_all(parsed.skus)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
    except Exception as e:
        logger.exception("Failed to write the live SKU snapshot")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not save the snapshot. The previous snapshot is unchanged.",
        ) from e

    logger.info(f"Live SKU snapshot uploaded: {count} SKU(s) from '{file.filename}'")
    await audit_repo.log_event(
        event_type="sku_snapshot_replaced",
        payload={"count": count, "skipped_rows": parsed.skipped_rows, "filename": file.filename},
        actor="operator",
    )
    return SnapshotUploadResult(
        success=True,
        count=count,
        skipped_rows=parsed.skipped_rows,
        had_header=parsed.had_header,
        warnings=parsed.warnings,
    )


class SourceModeSetting(BaseModel):
    mode: SourceMode


@router.get("/source-mode", response_model=SourceModeSetting)
async def get_source_mode() -> SourceModeSetting:
    stored = await settings_repo.get_setting(SOURCE_MODE_SETTING_KEY)
    mode: SourceMode = stored if stored in ("strict", "priority") else DEFAULT_SOURCE_MODE
    return SourceModeSetting(mode=mode)


@router.put("/source-mode", response_model=SourceModeSetting)
async def set_source_mode(payload: SourceModeSetting) -> SourceModeSetting:
    """
    Controls whether discovery may look beyond the configured sources.

    Defaults to `strict`, matching the rest of the system's no-guess principle:
    a product that cannot be verified from an approved source goes to Manual
    Review rather than being built from an unknown site.
    """
    await settings_repo.update_setting(SOURCE_MODE_SETTING_KEY, payload.mode)
    logger.info(f"Source mode set to '{payload.mode}'")
    # Switching out of strict mode widens what the system is allowed to read,
    # so it must be traceable to a moment and an actor.
    await audit_repo.log_event(
        event_type="source_mode_changed", payload={"mode": payload.mode}, actor="operator"
    )
    return payload


class ProvidedSourceModeSetting(BaseModel):
    mode: ProvidedSourceMode


@router.get("/provided-source-mode", response_model=ProvidedSourceModeSetting)
async def get_provided_source_mode() -> ProvidedSourceModeSetting:
    stored = await settings_repo.get_setting(PROVIDED_SOURCE_MODE_KEY)
    mode: ProvidedSourceMode = stored if stored in ("augment", "strict") else DEFAULT_PROVIDED_SOURCE_MODE
    return ProvidedSourceModeSetting(mode=mode)


@router.put("/provided-source-mode", response_model=ProvidedSourceModeSetting)
async def set_provided_source_mode(payload: ProvidedSourceModeSetting) -> ProvidedSourceModeSetting:
    """
    Controls how a product's operator-provided source (Website Link / Details) is used.

    `augment` (default): use the provided source AND still run discovery to
    cross-check it against independent sources. `strict`: use ONLY the provided
    source and run no discovery -- for when the operator fully trusts the link/
    details they pasted and wants nothing else consulted.
    """
    await settings_repo.update_setting(PROVIDED_SOURCE_MODE_KEY, payload.mode)
    logger.info(f"Provided-source mode set to '{payload.mode}'")
    await audit_repo.log_event(
        event_type="provided_source_mode_changed", payload={"mode": payload.mode}, actor="operator"
    )
    return payload


@router.get("/seo-title-descriptors")
async def get_seo_title_descriptors():
    """
    Read-only view of `seo_title_builder.py`'s CATEGORY_TITLE_DESCRIPTORS (the
    "Boss Title Rule" registry). Deliberately read-only, not a DB-backed CRUD:
    the title format is deterministic code, not user data, so adding a new
    category's descriptor is a one-line edit to that dict + a redeploy -- this
    endpoint exists so you can see what's registered without opening the code,
    not to pretend it's editable without one (that would be a false promise).
    """
    return {
        "category_descriptors": CATEGORY_TITLE_DESCRIPTORS,
        "fallback_power_word": POWER_WORD_SUFFIX,
    }


_REQUIRED_API_KEYS = [
    "GEMINI_API_KEY", "GROQ_API_KEY", "OPENAI_API_KEY", "FIRECRAWL_API_KEY", "GLITCHTIP_DSN",
    # Broad web discovery -- both needed together for the Google search tier to
    # activate; the Settings page shows the operator whether it is live.
    "GOOGLE_SEARCH_API_KEY", "GOOGLE_SEARCH_CX",
]


@router.get("/api-key-status")
async def get_api_key_status():
    """Presence-only check -- never returns the actual key values to the frontend."""
    return {key: bool(os.environ.get(key)) for key in _REQUIRED_API_KEYS}


class TrustLevelUpdate(BaseModel):
    mode: TrustLevel


@router.get("/trust-level")
async def get_trust_level():
    value = await settings_repo.get_setting("trust_level")
    # Default to Full Review Mode if never set -- the safe default (phase1.md §5.7:
    # "used during pilot and any period the user hasn't yet built trust in the system").
    mode = (value or {}).get("mode", "full_review") if isinstance(value, dict) else "full_review"
    return {"mode": mode}


@router.put("/trust-level")
async def set_trust_level(payload: TrustLevelUpdate):
    await settings_repo.update_setting("trust_level", {"mode": payload.mode})
    return {"mode": payload.mode}
