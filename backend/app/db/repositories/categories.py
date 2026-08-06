
from app.db.repositories.base import BaseRepository
from app.models.taxonomy import Category


class CategoriesRepository(BaseRepository[Category]):
    def __init__(self):
        super().__init__(model=Category, table_name="categories")

    async def get_by_name(self, name: str) -> Category | None:
        results = await self.list(filters={"name": name})
        return results[0] if results else None

    async def get_active_names_and_parents(self) -> tuple[list[str], dict[str, str]]:
        """
        Returns (active category names, {child name -> parent name}) for the
        input adapter.

        Read live on every import so categories added or renamed through the
        frontend Taxonomy Manager take effect immediately, with no redeploy and
        nothing hardcoded. Inactive categories are excluded so a deactivated
        category can never be auto-assigned to a new product.
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

categories_repo = CategoriesRepository()
