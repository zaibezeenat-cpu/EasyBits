
from app.db.repositories.base import BaseRepository
from app.models.template import Template


class TemplatesRepository(BaseRepository[Template]):
    def __init__(self):
        super().__init__(model=Template, table_name="templates")

    async def get_by_name(self, name: str) -> Template | None:
        """
        Bug fix: the previous version called `self.client.from_(...)`, but
        BaseRepository has no `self.client` attribute (it uses the module-level
        `supabase` import) and its "model" was a plain class incompatible with
        Pydantic's `.model_validate()` used throughout BaseRepository. Any
        product routed through Template B would have crashed the pipeline
        calling this method. Fixed to use the real repository pattern,
        consistent with every other repo in this codebase.
        """
        results = await self.list(filters={"name": name, "is_active": True})
        return results[0] if results else None

    async def get_active_by_type(self, template_type: str) -> list[Template]:
        return await self.list(filters={"template_type": template_type, "is_active": True})


templates_repo = TemplatesRepository()
