from uuid import UUID

from app.db.repositories.base import BaseRepository
from app.db.supabase_client import get_supabase
from app.models.batch import Batch, BatchStatus


class BatchesRepository(BaseRepository[Batch]):
    def __init__(self):
        super().__init__(model=Batch, table_name="batches")

    async def update_status(self, batch_id: UUID, status: str):
        await self.update(batch_id, {"status": status})

    async def finish(
        self,
        batch_id: UUID,
        *,
        status: str,
        total_products: int,
        succeeded_count: int,
        failed_count: int,
        manual_review_count: int,
    ) -> None:
        """
        Records the final tally for a completed run.

        The Batch model has always had total_products/succeeded_count/
        failed_count/manual_review_count, and the Dashboard's Recent Batches
        table (frontend/app/page.tsx) has always rendered them -- but nothing
        ever wrote them, so every batch row showed 0/0/0 regardless of what
        actually happened. This is the write side of that read path.
        """
        await self.update(batch_id, {
            "status": status,
            "total_products": total_products,
            "succeeded_count": succeeded_count,
            "failed_count": failed_count,
            "manual_review_count": manual_review_count,
        })

    async def create_batch(self, label: str) -> UUID:
        batch = await self.create({"label": label, "status": BatchStatus.PENDING})
        return batch.id

    async def list_recent(self, limit: int = 20) -> list[Batch]:
        db = await get_supabase()
        response = await db.table(self.table_name).select("*").order(
            "created_at", desc=True
        ).limit(limit).execute()
        return [self.model.model_validate(item) for item in response.data]

batches_repo = BatchesRepository()
