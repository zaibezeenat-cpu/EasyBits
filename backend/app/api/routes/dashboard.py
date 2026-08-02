from datetime import datetime, timedelta, timezone
from fastapi import APIRouter
from app.db.supabase_client import get_supabase

router = APIRouter()


@router.get("/stats")
async def get_dashboard_stats():
    """
    Real data for the Dashboard's 5 stat cards (phase2.md §5.2).
    No hardcoded/mock values — every number is a live query.
    """
    db = await get_supabase()

    manual_review = await db.table("manual_review_queue").select("id", count="exact").eq("status", "open").execute()
    manual_review_count = manual_review.count or 0

    ready_for_qa = await db.table("products").select("id", count="exact").eq("status", "ready_for_qa").execute()
    ready_for_qa_count = ready_for_qa.count or 0

    batches_in_progress = await db.table("batches").select("id", count="exact").eq("status", "processing").execute()
    batches_in_progress_count = batches_in_progress.count or 0

    week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()

    week_approved = await db.table("products").select("id", count="exact").in_(
        "status", ["approved", "exported"]
    ).gte("approved_at", week_ago).execute()
    week_approved_count = week_approved.count or 0

    # Avg QA time = approved_at - ready_for_qa_at, over the last 7 days' approved products.
    # Computed in Python (not a SQL aggregate) — fine at this data volume, and portable
    # if the DB backend ever changes (phase2.md's Appwrite discussion).
    qa_rows = await db.table("products").select("ready_for_qa_at, approved_at").in_(
        "status", ["approved", "exported"]
    ).gte("approved_at", week_ago).execute()

    durations = []
    for row in qa_rows.data or []:
        if row.get("ready_for_qa_at") and row.get("approved_at"):
            ready_at = datetime.fromisoformat(row["ready_for_qa_at"].replace("Z", "+00:00"))
            approved_at = datetime.fromisoformat(row["approved_at"].replace("Z", "+00:00"))
            durations.append((approved_at - ready_at).total_seconds())

    avg_qa_seconds = sum(durations) / len(durations) if durations else None

    return {
        "manual_review_count": manual_review_count,
        "ready_for_qa_count": ready_for_qa_count,
        "batches_in_progress_count": batches_in_progress_count,
        "week_approved_count": week_approved_count,
        "avg_qa_seconds": avg_qa_seconds,
    }
