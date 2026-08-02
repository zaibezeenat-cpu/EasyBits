import logging

from app.db.supabase_client import get_supabase

logger = logging.getLogger(__name__)

# Supabase's REST API rejects very large payloads, so writes are chunked.
_INSERT_CHUNK = 500


class SKUSnapshotRepository:
    def __init__(self):
        self.table_name = "live_sku_snapshot"

    async def exists(self, sku: str) -> bool:
        db = await get_supabase()
        response = await db.table(self.table_name).select("sku").eq("sku", sku).execute()
        return len(response.data) > 0

    async def count(self) -> int:
        db = await get_supabase()
        response = await db.table(self.table_name).select("sku", count="exact").limit(1).execute()
        return response.count or 0

    async def last_imported_at(self) -> str | None:
        db = await get_supabase()
        response = (
            await db.table(self.table_name)
            .select("imported_at")
            .order("imported_at", desc=True)
            .limit(1)
            .execute()
        )
        return response.data[0]["imported_at"] if response.data else None

    async def replace_all(self, skus: list[str]) -> int:
        """
        Replaces the snapshot with `skus`, returning how many are now stored.

        ORDER MATTERS, AND NOT THE OBVIOUS ONE. The intuitive implementation is
        DELETE-then-INSERT, but Supabase's REST API has no transactions, so that
        leaves a window in which the table is EMPTY. During that window the
        duplicate-SKU guard finds nothing to compare against and lets every SKU
        through -- which is precisely the failure this snapshot exists to
        prevent: a matching SKU silently OVERWRITES a live WooCommerce product.

        So this upserts the new SKUs FIRST, then removes the ones no longer
        present. During the overlap both old and new SKUs exist, so the guard
        over-blocks rather than under-blocks. Over-blocking sends a product to
        Manual Review, which is recoverable in a minute. Under-blocking destroys
        a live listing, which is not.

        Deleting is also skipped entirely when `skus` is empty, so a truncated
        or mis-parsed upload can never wipe a good snapshot.
        """
        if not skus:
            raise ValueError("Refusing to replace the snapshot with an empty list")

        db = await get_supabase()
        unique_skus = list(dict.fromkeys(s.strip() for s in skus if s and s.strip()))
        if not unique_skus:
            raise ValueError("Refusing to replace the snapshot with an empty list")

        # 1. Add/refresh every incoming SKU. `on_conflict` makes re-uploading
        #    the same list a no-op rather than a unique-violation error.
        for start in range(0, len(unique_skus), _INSERT_CHUNK):
            chunk = unique_skus[start:start + _INSERT_CHUNK]
            await db.table(self.table_name).upsert(
                [{"sku": sku} for sku in chunk], on_conflict="sku"
            ).execute()

        # 2. Only now remove SKUs that are no longer on the live store. Chunked
        #    because a `not_.in_` filter with thousands of values overflows the
        #    request URL.
        existing = await db.table(self.table_name).select("sku").execute()
        incoming = set(unique_skus)
        stale = [row["sku"] for row in (existing.data or []) if row["sku"] not in incoming]

        for start in range(0, len(stale), _INSERT_CHUNK):
            chunk = stale[start:start + _INSERT_CHUNK]
            await db.table(self.table_name).delete().in_("sku", chunk).execute()

        if stale:
            logger.info(f"SKU snapshot: removed {len(stale)} SKU(s) no longer on the live store")
        logger.info(f"SKU snapshot replaced: {len(unique_skus)} SKU(s) now stored")
        return len(unique_skus)


sku_snapshot_repo = SKUSnapshotRepository()
