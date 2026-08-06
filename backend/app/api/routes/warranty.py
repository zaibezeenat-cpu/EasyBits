from datetime import date, timedelta

from app.db.repositories.brands import brands_repo
from app.db.repositories.categories import categories_repo
from app.db.repositories.warranty import warranty_repo
from fastapi import APIRouter

router = APIRouter()


@router.get("/")
async def list_warranty_matrix():
    """
    Warranty Matrix for Settings (phase2.md §5.2) — joins brand/category names
    in Python since the DB is a plain FK-based schema, not denormalized, and
    flags entries older than 90 days for the quarterly re-audit (phase1.md §5.5).
    """
    rows = await warranty_repo.list_all()
    brands = {str(b.id): b.name for b in await brands_repo.list()}
    categories = {str(c.id): c.name for c in await categories_repo.list()}
    stale_cutoff = date.today() - timedelta(days=90)

    result = []
    for row in rows:
        last_audited = row.get("last_audited_at")
        is_stale = bool(last_audited) and date.fromisoformat(last_audited) < stale_cutoff
        result.append({
            "id": row["id"],
            "brand_name": brands.get(row.get("brand_id"), "Unknown"),
            "category_name": categories.get(row.get("category_id"), "All categories (brand default)"),
            "warranty_phrase": row["warranty_phrase"],
            "last_audited_at": last_audited,
            "is_stale": is_stale,
        })
    return result
