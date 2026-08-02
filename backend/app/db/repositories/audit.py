"""
Append-only record of the actions that change what reaches the live store.

WHY THIS EXISTS AT ALL: when a wrong product appears on kiachahiye.com, the only
useful question is "what changed, and when". Taxonomy edits, snapshot replacement
and source-mode changes all alter what future exports contain, and none of them
leaves any other trace.

This module previously had `log_event` and NOTHING CALLED IT, so the table was
permanently empty. Writers are now wired at the call sites below.
"""
import logging
from typing import Any, Dict, List, Optional

from app.db.supabase_client import get_supabase

logger = logging.getLogger(__name__)


class AuditRepository:
    def __init__(self):
        self.table_name = "audit_log"

    async def log_event(
        self,
        product_id: Optional[str] = None,
        batch_id: Optional[str] = None,
        event_type: str = "",
        payload: Optional[Dict[str, Any]] = None,
        actor: str = "system",
    ) -> None:
        """
        Records one event.

        NEVER RAISES. An audit write failing must not abort the operation it is
        describing -- refusing to save a taxonomy fix because the log was
        unreachable would turn an observability problem into a data problem.
        The failure is logged so a silently empty audit trail is still visible
        in the application logs.

        (The mutable-default `payload={}` this replaced was a latent bug: one
        dict shared across every call, so any mutation would leak between them.)
        """
        try:
            db = await get_supabase()
            await db.table(self.table_name).insert({
                "product_id": product_id,
                "batch_id": batch_id,
                "event_type": event_type,
                "payload": payload or {},
                "actor": actor,
            }).execute()
        except Exception as e:
            logger.warning(f"Could not write audit event '{event_type}': {e}")

    async def list_recent(self, limit: int = 100, event_type: Optional[str] = None) -> List[Dict[str, Any]]:
        db = await get_supabase()
        query = db.table(self.table_name).select("*").order("created_at", desc=True).limit(limit)
        if event_type:
            query = query.eq("event_type", event_type)
        response = await query.execute()
        return response.data


audit_repo = AuditRepository()
