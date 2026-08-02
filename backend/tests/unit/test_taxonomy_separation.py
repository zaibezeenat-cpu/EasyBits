"""
Proves brands and categories can never share a term, and that near-duplicate
casings cannot be created.

THE INCIDENT THIS PREVENTS
--------------------------
"Deerma" -- a manufacturer -- was seeded into the live category tree by mistake
and sat there undetected, because brand and category creation had no validation
of any kind. In WooCommerce a brand and a category are different taxonomies; a
manufacturer filed as a category becomes a category term in the live store.

The same endpoint also had no duplicate check, so "Air Conditioner" could be
created alongside the existing "Air conditioner", leaving two valid-looking
casings and guaranteeing that half the catalogue would eventually be filed
under the wrong one.
"""
import pytest
from fastapi import HTTPException

from app.api.routes import taxonomy


class _Row:
    def __init__(self, name: str):
        self.name = name


@pytest.fixture
def live_taxonomy(monkeypatch):
    """Stands in for the real tables with the names actually in the database."""
    brands = [_Row("Kenwood"), _Row("GREE"), _Row("DAWLANCE")]
    categories = [_Row("Air conditioner"), _Row("Washing machine")]

    class FakeBrands:
        async def list(self):
            return brands

    class FakeCategories:
        async def list(self):
            return categories

    monkeypatch.setattr(taxonomy, "brands_repo", FakeBrands())
    monkeypatch.setattr(taxonomy, "categories_repo", FakeCategories())
    return brands, categories


# --- Cross-taxonomy contamination -------------------------------------------


@pytest.mark.asyncio
async def test_a_brand_name_cannot_be_created_as_a_category(live_taxonomy):
    """The exact Deerma failure, in the shape it would take today."""
    with pytest.raises(HTTPException) as exc:
        await taxonomy._assert_taxonomy_name_is_new("Kenwood", kind="category")
    assert exc.value.status_code == 409
    assert "brand" in exc.value.detail.lower()


@pytest.mark.asyncio
async def test_a_category_name_cannot_be_created_as_a_brand(live_taxonomy):
    with pytest.raises(HTTPException) as exc:
        await taxonomy._assert_taxonomy_name_is_new("Air conditioner", kind="brand")
    assert exc.value.status_code == 409
    assert "category" in exc.value.detail.lower()


@pytest.mark.asyncio
async def test_contamination_is_caught_regardless_of_casing(live_taxonomy):
    """"deerma" and "Deerma" are the same mistake."""
    with pytest.raises(HTTPException):
        await taxonomy._assert_taxonomy_name_is_new("kenwood", kind="category")
    with pytest.raises(HTTPException):
        await taxonomy._assert_taxonomy_name_is_new("KENWOOD", kind="category")


# --- Near-duplicate casings -------------------------------------------------


@pytest.mark.asyncio
async def test_a_second_casing_of_an_existing_category_is_refused(live_taxonomy):
    """
    "Air Conditioner" (capital C) alongside "Air conditioner" would split the
    catalogue across two WooCommerce terms.
    """
    with pytest.raises(HTTPException) as exc:
        await taxonomy._assert_taxonomy_name_is_new("Air Conditioner", kind="category")
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_a_second_casing_of_an_existing_brand_is_refused(live_taxonomy):
    with pytest.raises(HTTPException):
        await taxonomy._assert_taxonomy_name_is_new("Gree", kind="brand")


@pytest.mark.asyncio
async def test_whitespace_variant_is_not_a_new_term(live_taxonomy):
    """Trailing whitespace is invisible in the UI but distinct to WooCommerce."""
    with pytest.raises(HTTPException):
        await taxonomy._assert_taxonomy_name_is_new("  Kenwood  ", kind="brand")


# --- Genuinely new names must still be allowed ------------------------------


@pytest.mark.asyncio
async def test_a_genuinely_new_name_is_accepted(live_taxonomy):
    """The guard must not block real additions -- the taxonomy is owner-editable."""
    await taxonomy._assert_taxonomy_name_is_new("Air Fryer", kind="category")
    await taxonomy._assert_taxonomy_name_is_new("Haier", kind="brand")
