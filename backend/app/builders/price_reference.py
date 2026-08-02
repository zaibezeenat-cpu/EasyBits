from decimal import Decimal
from typing import Optional

def compute_price_discrepancy(scraped_price: Optional[float], input_price: Optional[Decimal]) -> Optional[float]:
    """
    Computes percentage difference between official and input price (Phase 2 §6).
    """
    if not scraped_price or not input_price or input_price == 0:
        return None

    diff = abs(Decimal(str(scraped_price)) - input_price)
    pct = (diff / input_price) * 100
    return float(pct)

def get_price_warning(discrepancy_pct: Optional[float]) -> Optional[str]:
    if discrepancy_pct and discrepancy_pct > 15.0:
        return f"Warning: Price discrepancy is {discrepancy_pct:.1f}% (>15%)"
    return None
