import logging
from app.db.repositories.llm_usage import llm_usage_repo
from app.db.repositories.settings import settings_repo

logger = logging.getLogger(__name__)

async def check_budget_ok() -> bool:
    """
    Sums estimated_cost_usd for the current calendar month and compares against limit.
    """
    limit = await settings_repo.get_setting("monthly_api_budget_usd") or 5.00
    current_spend = await llm_usage_repo.get_monthly_spend()
    
    if current_spend >= float(limit):
        logger.warning(f"Budget exceeded: ${current_spend} >= ${limit}")
        return False
    return True
