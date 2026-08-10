import re
from typing import Any

from app.db.repositories.base import BaseRepository
from app.db.repositories._ttl_cache import TTLCache
from app.models.taxonomy import Brand

_WHITESPACE_RE = re.compile(r"\s+")


def _normalize_brand_key(name: str) -> str:
    """Case/whitespace-insensitive key for matching a typed brand name against
    the taxonomy's canonical name. Collapses internal whitespace too (a CSV
    copy-paste artifact like "Super  Asia" as much as a single trailing
    space) -- see get_by_name_ci()'s docstring for why this exists."""
    return _WHITESPACE_RE.sub(" ", (name or "").strip().lower())


class BrandsRepository(BaseRepository[Brand]):
    def __init__(self):
        super().__init__(model=Brand, table_name="brands")
        # See _ttl_cache.py: get_by_name is read up to ~4x per product
        # (intake_triage, writer_node -- once per retry, deterministic_builders_node,
        # csv_row_assembler_node) on data that cannot change mid-batch.
        self._by_name_cache = TTLCache()
        self._by_name_ci_cache = TTLCache()

    async def get_by_name(self, name: str) -> Brand | None:
        hit, cached = self._by_name_cache.get(name)
        if hit:
            return cached
        results = await self.list(filters={"name": name})
        brand = results[0] if results else None
        self._by_name_cache.set(name, brand)
        return brand

    async def get_by_name_ci(self, name: str) -> Brand | None:
        """
        Case/whitespace-insensitive brand lookup.

        2026-08-10 (owner-reported, live): intake used to call the strict
        get_by_name() only, an exact `.eq("name", ...)` DB filter -- so a
        CSV/manual brand string that differs from the taxonomy's stored
        casing, or just carries stray whitespace (a common copy-paste
        artifact), came back as "not found in DB" even though the brand
        plainly exists. This is for FINDABILITY only, not acceptability: the
        caller (intake_triage) still enforces the exact-casing Brand Casing
        Lock afterward, by comparing the returned Brand.name to the raw
        input string -- so a real casing/whitespace difference still
        surfaces, just as the specific, actionable brand_casing_mismatch
        ("does not exactly match live taxonomy casing 'X'") instead of a
        dead-end "brand does not exist".
        """
        key = _normalize_brand_key(name)
        if not key:
            return None
        hit, cached = self._by_name_ci_cache.get(key)
        if hit:
            return cached
        brands = await self.list()
        match = next((b for b in brands if _normalize_brand_key(b.name) == key), None)
        self._by_name_ci_cache.set(key, match)
        return match

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
        self._by_name_ci_cache.invalidate()
        return result

    async def update(self, id, data: dict[str, Any]) -> Brand:
        result = await super().update(id, data)
        self._by_name_cache.invalidate()
        self._by_name_ci_cache.invalidate()
        return result

brands_repo = BrandsRepository()
