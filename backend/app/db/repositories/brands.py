
from app.db.repositories.base import BaseRepository
from app.models.taxonomy import Brand


class BrandsRepository(BaseRepository[Brand]):
    def __init__(self):
        super().__init__(model=Brand, table_name="brands")

    async def get_by_name(self, name: str) -> Brand | None:
        results = await self.list(filters={"name": name})
        return results[0] if results else None

    async def get_active_names(self) -> list[str]:
        """
        Active brand names in their EXACT stored casing, for the input adapter.

        Read live on every import so brands added or re-cased through the
        frontend Taxonomy Manager apply immediately. Returning the stored string
        verbatim is what lets match_brand() satisfy the Brand Casing Lock -- the
        CSV then carries the same bytes the live WooCommerce taxonomy uses.
        """
        return [b.name for b in await self.list() if b.is_active]

brands_repo = BrandsRepository()
