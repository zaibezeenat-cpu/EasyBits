from datetime import UTC, datetime
from uuid import UUID

from app.db.repositories.base import BaseRepository
from app.models.product import Product


class ProductsRepository(BaseRepository[Product]):
    def __init__(self):
        super().__init__(model=Product, table_name="products")

    async def get_by_batch(self, batch_id: UUID) -> list[Product]:
        return await self.list(filters={"batch_id": str(batch_id)})

    async def update_product(self, product_id: UUID, data: dict) -> Product:
        # approved_at is set server-side, never trusted from client input, and only
        # the first time a product is approved -- this is what the Dashboard's
        # "Avg QA Time" stat (ready_for_qa_at -> approved_at) actually measures,
        # so it must not be overwritable by a later edit/re-approval.
        if data.get("status") == "approved":
            existing = await self.get(product_id)
            if existing and existing.approved_at is None:
                data = {**data, "approved_at": datetime.now(UTC).isoformat()}
        return await self.update(product_id, data)

products_repo = ProductsRepository()
