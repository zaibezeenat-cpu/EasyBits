"""
Verifies the TTL caching added to the taxonomy-adjacent repos (brands,
categories, taxonomy schemas, warranty matrix, brand domain aliases).

This is the fix for the ~38s-per-batch DB overhead: these repos are read
12-18 times PER PRODUCT (intake_triage, writer_node once per retry,
deterministic_builders_node, csv_row_assembler_node) on data that cannot
change mid-batch. Each test asserts the underlying Supabase client is hit
ONCE for N identical reads, and that a write invalidates the cache so a
Taxonomy Manager edit is never silently stale.
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.db.repositories.brands import BrandsRepository
from app.db.repositories.categories import CategoriesRepository
from app.db.repositories.sources import SourcesRepository
from app.db.repositories.taxonomy import TaxonomyRepository
from app.db.repositories.warranty import WarrantyRepository


def _fake_table(rows: list[dict]):
    """A minimal stand-in for `db.table(...).select(...)....execute()`."""
    execute = AsyncMock(return_value=MagicMock(data=rows))
    query = MagicMock()
    query.select.return_value = query
    query.eq.return_value = query
    query.is_.return_value = query
    query.order.return_value = query
    query.execute = execute
    return query, execute


@pytest.mark.asyncio
async def test_brands_get_by_name_hits_db_once_for_repeated_reads(monkeypatch):
    repo = BrandsRepository()
    query, execute = _fake_table([{
        "id": "00000000-0000-0000-0000-000000000001", "name": "HAIER",
        "display_name": None, "casing_confirmed": True, "is_active": True,
        "created_at": "2026-01-01T00:00:00Z", "updated_at": "2026-01-01T00:00:00Z",
    }])
    db = MagicMock()
    db.table.return_value = query
    monkeypatch.setattr("app.db.repositories.base.get_supabase", AsyncMock(return_value=db))

    for _ in range(4):  # simulates intake + 3 writer retries
        brand = await repo.get_by_name("HAIER")
        assert brand.name == "HAIER"

    assert execute.call_count == 1


@pytest.mark.asyncio
async def test_brands_update_invalidates_the_cache(monkeypatch):
    repo = BrandsRepository()
    query, execute = _fake_table([{
        "id": "00000000-0000-0000-0000-000000000001", "name": "HAIER",
        "display_name": None, "casing_confirmed": True, "is_active": True,
        "created_at": "2026-01-01T00:00:00Z", "updated_at": "2026-01-01T00:00:00Z",
    }])
    db = MagicMock()
    db.table.return_value = query
    monkeypatch.setattr("app.db.repositories.base.get_supabase", AsyncMock(return_value=db))

    await repo.get_by_name("HAIER")
    assert execute.call_count == 1

    update_execute = AsyncMock(return_value=MagicMock(data=[{
        "id": "00000000-0000-0000-0000-000000000001", "name": "HAIER",
        "display_name": "Haier", "casing_confirmed": True, "is_active": True,
        "created_at": "2026-01-01T00:00:00Z", "updated_at": "2026-01-01T00:00:00Z",
    }]))
    query.update.return_value = query
    query.execute = update_execute
    await repo.update("00000000-0000-0000-0000-000000000001", {"display_name": "Haier"})

    # Cache was cleared by the write -- the next read must hit the DB again,
    # or an operator's edit in the Taxonomy Manager would never take effect.
    query.execute = execute
    await repo.get_by_name("HAIER")
    assert execute.call_count == 2


@pytest.mark.asyncio
async def test_categories_get_by_id_hits_db_once_for_repeated_parent_lookups(monkeypatch):
    repo = CategoriesRepository()
    cat_id = "00000000-0000-0000-0000-000000000002"
    query, execute = _fake_table([{
        "id": cat_id, "name": "Refrigerator", "parent_id": None,
        "is_active": True, "needs_confirmation": False, "notes": None,
        "created_at": "2026-01-01T00:00:00Z", "updated_at": "2026-01-01T00:00:00Z",
    }])
    db = MagicMock()
    db.table.return_value = query
    monkeypatch.setattr("app.db.repositories.base.get_supabase", AsyncMock(return_value=db))

    from uuid import UUID
    for _ in range(3):  # deterministic_builders_node + csv_row_assembler_node
        category = await repo.get(UUID(cat_id))
        assert category.name == "Refrigerator"

    assert execute.call_count == 1


@pytest.mark.asyncio
async def test_taxonomy_schema_cached(monkeypatch):
    repo = TaxonomyRepository()
    query, execute = _fake_table([{
        "id": "00000000-0000-0000-0000-000000000003",
        "category_id": "00000000-0000-0000-0000-000000000002",
        "fields": [{"key": "capacity", "label": "Capacity", "required": True}],
        "created_at": "2026-01-01T00:00:00Z", "updated_at": "2026-01-01T00:00:00Z",
    }])
    db = MagicMock()
    db.table.return_value = query
    monkeypatch.setattr("app.db.repositories.taxonomy.get_supabase", AsyncMock(return_value=db))

    from uuid import UUID
    for _ in range(2):  # intake_triage + extractor_node prompt-building
        schema = await repo.get_schema_by_category(UUID("00000000-0000-0000-0000-000000000002"))
        assert schema.fields[0].key == "capacity"

    assert execute.call_count == 1


@pytest.mark.asyncio
async def test_warranty_phrase_cached_per_brand_category_pair(monkeypatch):
    repo = WarrantyRepository()
    query, execute = _fake_table([{"warranty_phrase": "1-Year Brand Warranty"}])
    db = MagicMock()
    db.table.return_value = query
    monkeypatch.setattr("app.db.repositories.warranty.get_supabase", AsyncMock(return_value=db))

    from uuid import UUID
    brand_id = UUID("00000000-0000-0000-0000-000000000001")
    category_id = UUID("00000000-0000-0000-0000-000000000002")
    for _ in range(3):  # once per Writer/Reviewer retry
        phrase = await repo.get_phrase(brand_id, category_id)
        assert phrase == "1-Year Brand Warranty"

    assert execute.call_count == 1


@pytest.mark.asyncio
async def test_brand_aliases_cached_and_invalidated_on_write(monkeypatch):
    repo = SourcesRepository()
    brand_query, brand_execute = _fake_table([{"id": "brand-1"}])
    alias_query, alias_execute = _fake_table([{"official_domain": "Haier.com.pk"}])

    db = MagicMock()

    def table(name):
        return {"brands": brand_query, "brand_domain_aliases": alias_query}[name]
    db.table.side_effect = table
    monkeypatch.setattr("app.db.repositories.sources.get_supabase", AsyncMock(return_value=db))

    for _ in range(2):
        domains = await repo.get_brand_aliases("HAIER")
        assert domains == ["haier.com.pk"]
    assert brand_execute.call_count == 1
    assert alias_execute.call_count == 1

    upsert_query, upsert_execute = _fake_table([{"brand_id": "brand-1", "official_domain": "haier.com.pk"}])
    upsert_query.upsert.return_value = upsert_query
    db.table.side_effect = lambda name: {
        "brands": brand_query, "brand_domain_aliases": upsert_query
    }[name]
    await repo.set_brand_domain("brand-1", "haier.com.pk")

    db.table.side_effect = table
    await repo.get_brand_aliases("HAIER")
    assert brand_execute.call_count == 2
    assert alias_execute.call_count == 2
