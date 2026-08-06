"""
Tier-2 category resolution: an LLM picks the best category from the owner's
EXACT list when deterministic name-matching (input_adapter.infer_category) finds
nothing -- e.g. a hair straightener whose title never contains the word "Beauty".

Safety: the model is constrained to copy a category verbatim from the list or say
UNKNOWN; anything not found in the list resolves to None so the product goes to
Manual Review rather than into a wrong (or invented) WooCommerce category.
"""
import logging

from app.core.llm_provider import llm_provider
from pydantic import BaseModel

logger = logging.getLogger(__name__)


class CategoryChoice(BaseModel):
    """The single category the model chose, or 'UNKNOWN'."""
    category: str


_SYSTEM_PROMPT = (
    "You are a strict product categoriser for a Pakistani home-appliance and beauty "
    "store. You are given a product name and the EXACT list of allowed categories.\n"
    "Rules:\n"
    "1. Choose the SINGLE best-matching category.\n"
    "2. Copy it VERBATIM from the list -- do not rephrase, pluralise, or invent.\n"
    "3. If no category clearly fits, return exactly 'UNKNOWN'.\n"
    "Never return a value that is not in the list (other than 'UNKNOWN')."
)


async def llm_pick_category(product_name: str, known_categories: list[str]) -> str | None:
    """Pick a category from ``known_categories`` for ``product_name`` via the LLM.

    Returns the category EXACTLY as stored in the list (canonical casing), or None
    when the list is empty, the model says UNKNOWN, or it returns anything not in
    the list. Never raises to the caller for a model/transport error -- it logs and
    returns None so the row simply escalates.
    """
    if not known_categories:
        return None

    catalogue = "\n".join(f"- {c}" for c in known_categories)
    human_prompt = f"Product: {product_name}\n\nAllowed categories:\n{catalogue}"

    try:
        choice = await llm_provider.call(
            role="categorizer",
            system_prompt=_SYSTEM_PROMPT,
            human_prompt=human_prompt,
            response_model=CategoryChoice,
        )
    except Exception as e:
        logger.warning(f"LLM category pick failed for {product_name!r}: {e}")
        return None

    picked = (choice.category or "").strip()
    if not picked or picked.upper() == "UNKNOWN":
        return None

    # Canonicalise to the exact stored value; reject anything not in the list
    # (guards against a hallucinated or rephrased category).
    for category in known_categories:
        if category.lower() == picked.lower():
            return category

    logger.info(f"LLM picked '{picked}' which is not in the allowed list; treating as no match.")
    return None
