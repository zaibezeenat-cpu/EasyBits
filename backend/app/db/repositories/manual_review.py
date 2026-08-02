"""
Writes escalations into the manual_review_queue.

WHY THIS IS DEFENSIVE (found by the Haier pilot, 2026-07-22)
------------------------------------------------------------
`reason_code` is a Postgres ENUM. When application code introduced new failure
categories (`warranty_conflict`, `brand_casing_mismatch`,
`production_lock_violation`) the enum in the database was never extended, so the
INSERT failed with:

    invalid input value for enum manual_review_reason_code: "warranty_conflict"

That exception propagated out of the pipeline node, the product's status update
never ran, and the product was stranded in QUEUED -- neither exported nor in the
review queue. The single most dangerous outcome: a product that silently
vanishes. Unit tests missed it because they mock the database and never exercise
the real enum.

So escalation now NEVER crashes on an unknown reason code. It tries the real
code first (so once the enum is extended the value is stored first-class), and
on failure falls back to 'other' while preserving the real category inside
reason_detail, so nothing is lost and the reviewer still sees what happened.
"""
import logging

from app.db.supabase_client import get_supabase

logger = logging.getLogger(__name__)

# The safe fallback value -- guaranteed to exist in the enum since the schema
# was created.
_FALLBACK_REASON_CODE = "other"


class ManualReviewRepository:
    async def add(self, product_id: str, batch_id: str, reason_code: str, reason_detail: str) -> None:
        db = await get_supabase()
        row = {
            "product_id": product_id,
            "batch_id": batch_id,
            "reason_code": reason_code,
            "reason_detail": reason_detail,
            "status": "open",
        }
        try:
            await db.table("manual_review_queue").insert(row).execute()
            return
        except Exception as e:
            # Almost always an enum value the database does not know yet. Retry
            # with the safe code, keeping the real one visible in the detail so
            # the reviewer -- and any later migration audit -- can still see it.
            logger.warning(
                f"manual_review insert failed for reason_code '{reason_code}' "
                f"({e}); retrying as '{_FALLBACK_REASON_CODE}' with the code preserved in detail."
            )

        row["reason_code"] = _FALLBACK_REASON_CODE
        row["reason_detail"] = f"[{reason_code}] {reason_detail}"
        try:
            await db.table("manual_review_queue").insert(row).execute()
        except Exception as e:
            # Even the fallback failed. Do NOT re-raise: a failed queue write must
            # not crash the pipeline node and strand the product in QUEUED. The
            # product's own failure_reason column (written separately, and only a
            # TEXT field) still records why it escalated.
            logger.error(f"manual_review insert failed even with fallback code: {e}")


manual_review_repo = ManualReviewRepository()
