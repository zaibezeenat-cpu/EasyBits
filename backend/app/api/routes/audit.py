"""
Read-only view of the audit trail.

Deliberately has no POST: entries are written by the operations they describe,
never submitted by a client. An endpoint that let callers write their own audit
entries would make the log worth exactly as much as whoever called it.
"""
from typing import Optional

from fastapi import APIRouter, Query

from app.db.repositories.audit import audit_repo

router = APIRouter()


@router.get("/")
async def list_audit_events(
    limit: int = Query(default=100, ge=1, le=500),
    event_type: Optional[str] = Query(default=None, max_length=64),
):
    """Most recent events first. `limit` is bounded so one call cannot pull the whole table."""
    return await audit_repo.list_recent(limit=limit, event_type=event_type)
