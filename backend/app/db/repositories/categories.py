from uuid import UUID
from typing import Any

from app.db.repositories.base import BaseRepository
from app.db.repositories._ttl_cache import TTLCache
from app.models.taxonomy import Category

class CategoriesRepository(BaseRepository[Category]):
    def __init__(self):
        super().__init__(model=Category, table_name="categories")
        # See _ttl_cache.py: get_by_name / get (by id, for parent-category
        # lookups) are each read ~3x per product (deterministic_builders_node,
        # csv_row_assembler_node -- and get_by_name again at intake) on data
        # that cannot change mid-batch.
        self._by_name_cache = TTLCache()
        self._by_id_cache = TTLCache()

    async def get(self, id: UUID) -> Category | None:
        key = str(id)
        hit, cached = self._by_id_cache.get(key)
        if hit:
            return cached
        result = await super().get(id)
        self._by_id_cache.set(key, result)
        return result

    async def get_by_name(self, name: str) -> Category | None:
        hit, cached = self._by_name_cache.get(name)
        if hit:
            return cached
        results = await self.list(filters={"name": name})
        category = results[0] if results else None
        self._by_name_cache.set(name, category)
        return category

    async def get_active_names_and_parents(self) -> tuple[list[str], dict[str, str]]:
        """
        Returns (active category names, {child name -> parent name}) for the
        input adapter.

        Read live on every import so categories added or renamed through the
        frontend Taxonomy Manager take effect immediately, with no redeploy and
        nothing hardcoded. Inactive categories are excluded so a deactivated
        category can never be auto-assigned to a new product.

        Deliberately NOT cached: called once per bulk-import preview request,
        not per product.
        """
        all_categories = await self.list()
        by_id = {c.id: c for c in all_categories}

        names: list[str] = []
        parents: dict[str, str] = {}
        for category in all_categories:
            if not category.is_active:
                continue
            names.append(category.name)
            if category.parent_id and category.parent_id in by_id:
                parents[category.name] = by_id[category.parent_id].name
        return names, parents

    async def create(self, data: dict[str, Any]) -> Category:
        result = await super().create(data)
        self._by_name_cache.invalidate()
        self._by_id_cache.invalidate()
        return result

    async def update(self, id: UUID, data: dict[str, Any]) -> Category:
        result = await super().update(id, data)
        self._by_name_cache.invalidate()
        self._by_id_cache.invalidate()
        return result

categories_repo = CategoriesRepository()
