from typing import Any

from app.db.repositories.base import BaseRepository
from app.db.repositories._ttl_cache import TTLCache
from app.models.taxonomy import Brand


class BrandsRepository(BaseRepository[Brand]):
    def __init__(self):
        super().__init__(model=Brand, table_name="brands")
        # See _ttl_cache.py: get_by_name is read up to ~4x per product
        # (intake_triage, writer_node -- once per retry, deterministic_builders_node,
        # csv_row_assembler_node) on data that cannot change mid-batch.
        self._by_name_cache = TTLCache()

    async def get_by_name(self, name: str) -> Brand | None:
        hit, cached = self._by_name_cache.get(name)
        if hit:
            return cached
        results = await self.list(filters={"name": name})
        brand = results[0] if results else None
        self._by_name_cache.set(name, brand)
        return brand

    async def get_active_names(self) -> list[str]:
        """
        Active brand names in their EXACT stored casing, for the input adapter.

        Read live on every import so brands added or re-cased through the
        frontend Taxonomy Manager apply immediately. Returning the stored string
        verbatim is what lets match_brand() satisfy the Brand Casing Lock -- the
        CSV then carries the same bytes the live WooCommerce taxonomy uses.

        Deliberately NOT cached: called once per bulk-import preview request,
        not per product, so there is no hot-path win, and the whole point of
        "live" here is to reflect a just-added brand immediately.
        """
        return [b.name for b in await self.list() if b.is_active]

    async def create(self, data: dict[str, Any]) -> Brand:
        result = await super().create(data)
        self._by_name_cache.invalidate()
        return result

    async def update(self, id, data: dict[str, Any]) -> Brand:
        result = await super().update(id, data)
        self._by_name_cache.invalidate()
        return result

brands_repo = BrandsRepository()
